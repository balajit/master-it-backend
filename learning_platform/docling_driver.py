from pathlib import Path

from learning_platform.models.document import CanonicalDocument
from learning_platform.stages.parser.docling_adapter import DoclingAdapter

PDF_DIR = "/Users/rajani/workspace/apps/master-it-backend/test_pdfs/"


def process() -> CanonicalDocument:
    f = [str(f) for f in Path(PDF_DIR).iterdir() if f.is_file()]
    print(f"files :{f}")

    file_name = input("Enter the pdf file name: ")

    adapter = DoclingAdapter()
    return adapter.parse(PDF_DIR + file_name)


if __name__ == "__main__":
    doc = process()
    print(doc.to_string())
