import os
from io import BytesIO
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor


def build_presentation(slides_data: list, logo_path: str = None) -> BytesIO:
    """
    Builds a .pptx file in memory from the slides_data list.
    Each item in slides_data must have 'title' and 'content' keys.
    Returns a BytesIO stream ready for st.download_button.
    """
    prs = Presentation()

    # --- Title Slide ---
    title_layout = prs.slide_layouts[0]
    title_slide = prs.slides.add_slide(title_layout)
    title_slide.shapes.title.text = "Strategic AI Research Report"
    title_slide.placeholders[1].text = "Powered by AgenticDeck & Google Gemini"

    # --- Content Slides ---
    content_layout = prs.slide_layouts[1]

    for slide_info in slides_data:
        slide = prs.slides.add_slide(content_layout)

        # Title
        slide.shapes.title.text = slide_info.get("title", "Untitled Slide")

        # Content bullets
        tf = slide.placeholders[1].text_frame
        tf.word_wrap = True

        content = slide_info.get("content", "")

        # Normalize: handle both list and newline-separated string
        if isinstance(content, list):
            lines = content
        else:
            lines = [line for line in content.split("\n") if line.strip()]

        for i, line in enumerate(lines):
            clean_line = line.lstrip("-*•· ").strip()
            if not clean_line:
                continue
            if i == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.text = clean_line
            p.level = 0

        # Logo (bottom-right corner)
        if logo_path and os.path.exists(logo_path):
            try:
                slide.shapes.add_picture(
                    logo_path,
                    left=Inches(8.5),
                    top=Inches(6.5),
                    width=Inches(1.0)
                )
            except Exception as e:
                print(f"Could not add logo: {e}")

    # Save to in-memory stream
    ppt_stream = BytesIO()
    prs.save(ppt_stream)
    ppt_stream.seek(0)
    return ppt_stream