import logging

from learning_platform.models.document import CanonicalDocument
from learning_platform.stages.normalizer import StructuralNormalizer
from learning_platform.stages.parser2 import Parser2Adapter

logging.basicConfig(level=logging.INFO, force=True)

# Your module code
logger = logging.getLogger(__name__)

logger.setLevel(level=logging.INFO)
logger.info("TEST INFO")
logger.warning("TEST WARNING")


def normalize() -> CanonicalDocument:
    parser = Parser2Adapter()
    document = parser.parse("/Users/rajani/workspace/apps/master-it-backend/test_pdfs/small.pdf")
    normalizer = StructuralNormalizer()
    return normalizer.normalize(document)


if __name__ == "__main__":
    doc: CanonicalDocument = normalize()

    for node in doc.nodes:
        print(node.to_string())
        for c_node in node.children:
            print("Child ----> " + c_node.to_string())
