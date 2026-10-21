"""caudit —— 多份材料的字段一致性核查。"""

from .detect import Finding, Occurrence, Report, audit
from .dictionary import Field, find_values, load_dictionary
from .extract import Segment, extract_dir, extract_file
from .normalize import normalize, same_char_multiset

__version__ = "0.1.0"

__all__ = [
    "Field",
    "Finding",
    "Occurrence",
    "Report",
    "Segment",
    "audit",
    "extract_dir",
    "extract_file",
    "find_values",
    "load_dictionary",
    "normalize",
    "same_char_multiset",
    "__version__",
]
