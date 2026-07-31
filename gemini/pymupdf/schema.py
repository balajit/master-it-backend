from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    l: float = Field(..., description="Left coordinate (x0)")
    t: float = Field(..., description="Top coordinate (y0)")
    r: float = Field(..., description="Right coordinate (x1)")
    b: float = Field(..., description="Bottom coordinate (y1)")
    origin: str = Field(default="TOP_LEFT", description="Coordinate system origin")


class FontSpec(BaseModel):
    font_name: str
    size: float
    color: str = Field(..., description="Hex color code, e.g., #000000")


class TextStyle(BaseModel):
    font_id: str
    is_bold: bool = False
    is_italic: bool = False
    is_monospace: bool = False


class ImageMetadata(BaseModel):
    pixel_width: int
    pixel_height: int
    rendered_width_pt: float
    rendered_height_pt: float
    format: str
    asset_path: str


class TableMetadata(BaseModel):
    num_rows: int
    num_cols: int
    csv_repr: Optional[str] = Field(default=None, description="CSV representation of table")
    html_repr: Optional[str] = Field(default=None, description="HTML representation of table")
    grid_cells: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Raw cell matrix with row/col spans")


class EquationMetadata(BaseModel):
    latex_repr: Optional[str] = Field(default=None, description="LaTeX string if extracted by Docling")
    is_inline: bool = Field(default=False, description="True if inline math, False if standalone display block")


class DocumentElement(BaseModel):
    element_id: str
    type: Literal["text_span", "image", "table", "formula", "code_block"]
    label: str = Field(
        default="PARAGRAPH",
        description="Docling label (TITLE, SECTION_HEADER, FORMULA, TABLE, CODE, CAPTION, etc.)"
    )
    parent_hierarchy_ref: Optional[str] = Field(default=None, description="Docling JSON Pointer to parent item")
    text: Optional[str] = None
    bbox: BoundingBox
    style: Optional[TextStyle] = None
    image_metadata: Optional[ImageMetadata] = None
    table_metadata: Optional[TableMetadata] = None
    equation_metadata: Optional[EquationMetadata] = None


class PageDimensions(BaseModel):
    width: float
    height: float
    unit: str = "pt"


class LearningUnit(BaseModel):
    unit_id: str
    page_number: int
    page_dimensions: PageDimensions
    typography_manifest: Dict[str, FontSpec] = Field(default_factory=dict)
    elements: List[DocumentElement] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    document_id: str
    filename: str
    total_pages: int
    learning_units: List[LearningUnit] = Field(default_factory=list)