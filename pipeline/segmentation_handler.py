import logging
from modules.utils.text_segmentation import segment_page
from .webtoon_utils import (
    filter_and_convert_visible_blocks, 
    restore_original_block_coordinates
)

logger = logging.getLogger(__name__)


class SegmentationHandler:
    """Handles text segmentation processing for both regular and webtoon modes."""
    
    def __init__(self, main_page, pipeline):
        self.main_page = main_page
        self.pipeline = pipeline

    def segment_webtoon_visible_area(self):
        """Perform segmentation on the visible area in webtoon mode."""
        
        if not (self.main_page.image_viewer.hasPhoto() and 
                self.main_page.webtoon_mode):
            logger.warning("segment_webtoon_visible_area called but not in webtoon mode")
            return []
        
        # Get the visible area image and mapping data
        visible_image, mappings = self.main_page.image_viewer.get_visible_area_image()
        if visible_image is None or not mappings:
            logger.warning("No visible area found for segmentation")
            return []
        
        # Filter blocks to only those in the visible area and convert coordinates
        visible_blocks = filter_and_convert_visible_blocks(
            self.main_page, self.pipeline, mappings, single_block=False
        )
        if not visible_blocks:
            logger.info("No blocks found in visible area for segmentation")
            return []
        
        # Strokes are built while the blocks are in the visible image's
        # coordinates, from the text model's prediction for that image, then
        # placed back in the scene. Thresholding each box instead (what this
        # used to leave to the GUI thread) painted artwork with the lettering.
        page_text_mask = segment_page(visible_image, self.main_page.settings_page)
        offset = (0, mappings[0]['scene_y_start'])
        build_stroke = self.main_page.image_viewer.drawing_manager.make_segmentation_stroke_data
        strokes = [
            build_stroke(blk, visible_image, page_text_mask=page_text_mask, scene_offset=offset)
            for blk in visible_blocks
        ]
        restore_original_block_coordinates(visible_blocks)
        
        logger.info(f"Segmentation completed for {len(visible_blocks)} blocks in visible area")
        
        return list(zip(visible_blocks, strokes))
