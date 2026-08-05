from dataclasses import dataclass, field, asdict


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class Style:
    font_name: str = "Noto Sans Arabic"
    font_size: int = 42
    primary_color: str = "#FFFFFF"   # text fill
    outline_color: str = "#000000"   # text outline
    back_color: str = "#000000"      # background box
    back_alpha: int = 0              # 0 = no box, 255 = opaque
    outline_width: float = 2.0
    bold: bool = False
    italic: bool = False
    alignment: int = 2               # ASS numpad: 2=bottom-center, 8=top-center
    margin_v: int = 40               # vertical margin from edge (px)
    margin_h: int = 40

    def to_dict(self) -> dict:
        return asdict(self)
