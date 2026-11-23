import numpy as np
import logging
from ..utils.device import get_providers

from ..utils.inpainting import (
    norm_img,
    load_jit_model,
)
from ..utils.download import ModelDownloader, ModelID
from modules.utils.onnx import make_session, make_session_options
from modules.utils.torch_autocast import TorchAutocastMixin
from .base import InpaintModel
from .schema import Config

logger = logging.getLogger(__name__)


class LaMa(TorchAutocastMixin, InpaintModel):
    name = "lama"
    pad_mod = 8

    @staticmethod
    def should_use_autocast(device: str) -> bool:
        return str(device).split(":", 1)[0].lower() != "xpu"

    def init_model(self, device, **kwargs):
        self.backend = kwargs.get("backend")
        if self.backend == "onnx":
            ModelDownloader.get(ModelID.LAMA_ONNX)
            onnx_path = ModelDownloader.primary_path(ModelID.LAMA_ONNX)
            providers = get_providers(device)
            # ONNX Runtime with its memory arena off, not OpenVINO. Measured
            # over patches of seven sizes on a 4-core CPU: OpenVINO kept the
            # memory of every patch size it had seen (2.3 GB, a full-size page
            # 5 GB) for under 5% of speed; the arena kept 1.1 GB; without it
            # LaMa holds ~0.5 GB between patches and takes about as long. On a
            # PC with 8 GB, and a browser open, that is the difference.
            self.session = make_session(
                onnx_path, providers=providers, sess_options=make_session_options(low_mem=True),
            )
        else:
            import torch
            ModelDownloader.get(ModelID.LAMA_JIT)
            local_path = ModelDownloader.primary_path(ModelID.LAMA_JIT) 
            self.model = load_jit_model(local_path, device)
            self.setup_torch_autocast(torch, device)
            if not self.should_use_autocast(device):
                logger.info(
                    "Disabling LaMa autocast on device '%s' because the TorchScript FFT path requires float32.",
                    device,
                )
                self.use_autocast = False

    @staticmethod
    def is_downloaded() -> bool:
        return ModelDownloader.is_downloaded(ModelID.LAMA_JIT)

    def forward(self, image, mask, config: Config):
        """Input image and output image have same size
        image: [H, W, C] RGB
        mask: [H, W]
        return: BGR IMAGE
        """
        image_n = norm_img(image)
        mask_n = norm_img(mask)
        # mask_n = (mask_n > 0) * 1
        mask_n = (mask_n > 0).astype('float32')
        backend = getattr(self, 'backend', 'onnx')
        if backend == 'onnx':
            image_tensor = image_n[np.newaxis, ...]
            mask_tensor = mask_n[np.newaxis, ...]
            ort_inputs = {self.session.get_inputs()[0].name: image_tensor,
                          self.session.get_inputs()[1].name: mask_tensor}
            inpainted = self.session.run(None, ort_inputs)[0]
            cur_res = inpainted[0].transpose(1, 2, 0)
            cur_res = np.clip(cur_res * 255, 0, 255).astype("uint8")
            # cur_res is already in RGB format
            return cur_res
        else:
            import torch  # noqa
            image_t = torch.from_numpy(image_n).unsqueeze(0).to(self.device)
            mask_t = torch.from_numpy(mask_n).unsqueeze(0).to(self.device)
            with torch.inference_mode():
                inpainted_image = self.run_with_torch_autocast(
                    torch_module=torch,
                    fn=lambda: self.model(image_t, mask_t),
                    logger=logger,
                    engine_name=self.__class__.__name__,
                )
            cur_res = inpainted_image[0].permute(1, 2, 0).detach().cpu().numpy()
            cur_res = np.clip(cur_res * 255, 0, 255).astype("uint8")
            # cur_res is already in RGB format
            return cur_res
    
