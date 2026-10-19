import logging
from typing import Any
import numpy as np
from abc import abstractmethod
import base64
import imkit as imk

from ..base import LLMTranslation
from ...utils.textblock import TextBlock
from ...utils.translator_utils import get_raw_text, set_texts_from_json
from ...utils.thai_speech import targets_thai
from ...utils.speaker_map import (
    apply_speaker_map, build_speaker_prompt, parse_speaker_reply, speaker_map_block,
)

logger = logging.getLogger(__name__)

SPEAKER_SYSTEM_PROMPT = "You identify who speaks in comics. Reply with JSON only."


def build_user_prompt(raw_text: str, extra_context: str = "") -> str:
    """The user message for an LLM translation.

    The context (which carries the glossary) comes after the request for
    natural wording, right before the text: the last instruction the model
    reads is the one it weighs most, and the glossary has to win when the two
    disagree. It used to come first, and a term's fixed translation lost to
    "sound natural" often enough to be the complaint.
    """
    parts = ["Make the translation sound as natural as possible."]
    if extra_context and extra_context.strip():
        parts.append(extra_context.strip())
    parts.append(f"Translate this:\n{raw_text}")
    return "\n\n".join(parts)


class BaseLLMTranslation(LLMTranslation):
    """Base class for LLM-based translation engines with shared functionality."""

    def get_system_prompt(self, source_lang: str, target_lang: str) -> str:
        # Use the user's active prompt preset (manga/manhwa/webtoon/custom).
        from ...utils.prompts import PromptManager
        return PromptManager.instance().build_system_prompt(source_lang, target_lang)
    
    def __init__(self):
        self.source_lang = None
        self.target_lang = None
        self.api_key = None
        self.api_url = None
        self.model = None
        self.img_as_llm_input = False
        self.temperature = None
        self.top_p = None
        self.max_tokens = None
        self.timeout = 30  
        # Glossary characters with their gender (speaker_map.Character), set by
        # Translator before each page; read by identify_speakers.
        self.speaker_characters = []
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, **kwargs) -> None:
        """
        Initialize the LLM translation engine.
        
        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
            **kwargs: Engine-specific initialization parameters
        """
        llm_settings = settings.get_llm_settings()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.img_as_llm_input = llm_settings.get('image_input_enabled', True)
        self.temperature = 1.0
        self.top_p = 0.95
        self.max_tokens = 5000
        
    def translate(self, blk_list: list[TextBlock], image: np.ndarray, extra_context: str) -> list[TextBlock]:
        """
        Translate text blocks using LLM.
        
        Args:
            blk_list: List of TextBlock objects to translate
            image: Image as numpy array
            extra_context: Additional context information for translation
            
        Returns:
            List of updated TextBlock objects with translations
        """
        entire_raw_text = get_raw_text(blk_list)
        system_prompt = self.get_system_prompt(self.source_lang, self.target_lang)
        # Into Thai, who speaks each block is decided first, in a request of
        # its own: the model credits a bubble to the name inside it when it
        # has to work that out while translating (see speaker_map).
        speakers = self.identify_speakers(blk_list, image) if targets_thai(self.target_lang or "") else None
        speaker_block = speaker_map_block(speakers)
        context = "\n\n".join(p for p in (extra_context, speaker_block) if p and p.strip())
        user_prompt = build_user_prompt(entire_raw_text, context)
        
        entire_translated_text = self._perform_translation(user_prompt, system_prompt, image)
        set_texts_from_json(blk_list, entire_translated_text)
        fixed = apply_speaker_map(blk_list, speakers)
        if fixed:
            logger.info("Speaker map: fixed ครับ/ค่ะ in %d block(s)", fixed)
            
        return blk_list

    def identify_speakers(self, blk_list: list[TextBlock], image: np.ndarray):
        """Who speaks each block, asked on its own; None when that fails.

        A failure here never stops the translation: it goes ahead without a
        map, as it did before there was one.
        """
        texts = [blk.text or "" for blk in blk_list]
        if not any(t.strip() for t in texts):
            return None
        page_text = " ".join(texts)
        shown, seen = [], set()
        for c in self.speaker_characters:
            if c.source and c.source in page_text and (c.target, c.gender) not in seen:
                shown.append(c)
                seen.add((c.target, c.gender))
        prompt = build_speaker_prompt(self.source_lang, texts, shown)
        saved = self.temperature
        self.temperature = 0
        try:
            reply = self._perform_translation(prompt, SPEAKER_SYSTEM_PROMPT, image)
        except Exception as e:  # noqa: BLE001 - any failure means "no map"
            logger.warning("Speaker identification failed, translating without it: %s", e)
            return None
        finally:
            self.temperature = saved
        speakers = parse_speaker_reply(reply, len(blk_list), self.speaker_characters)
        if speakers is None:
            logger.warning("Speaker identification returned no readable JSON; translating without it")
        return speakers
    
    @abstractmethod
    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        """
        Perform translation using specific LLM.
        
        Args:
            user_prompt: User prompt for LLM
            system_prompt: System prompt for LLM
            image: Image as numpy array
            
        Returns:
            Translated JSON text
        """
        pass

    def encode_image(self, image: np.ndarray, ext=".jpg"):
        """
        Encode CV2/numpy image directly to base64 string using cv2.imencode.
        
        Args:
            image: Numpy array representing the image
            ext: Extension/format to encode the image as (".png" by default for higher quality)
                
        Returns:
            Tuple of (Base64 encoded string, mime_type)
        """
        # Direct encoding from numpy/cv2 format to bytes
        buffer = imk.encode_image(image, ext.lstrip('.'))
        
        # Convert to base64
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        # Map extension to mime type
        mime_types = {
            ".jpg": "image/jpeg", 
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }
        mime_type = mime_types.get(ext.lower(), f"image/{ext[1:].lower()}")
        
        return img_str, mime_type