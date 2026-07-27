import json
import logging
from pathlib import Path
from typing import Any

from learning_platform.api.deps import get_pipeline_orchestrator
from learning_platform.pipeline.orchestrator import PipelineOrchestrator, PipelineResult

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

PDF_DIR="/Users/rajani/workspace/apps/master-it-backend/test_pdfs/"

def get_file() -> str:
    f = [str(f) for f in Path(PDF_DIR).iterdir() if f.is_file() and f.name.endswith(".pdf")]
    print(f"files :{f}")


    file_name = input("Enter the pdf file name: ")
    return PDF_DIR + file_name


def print_json(obj: Any) -> None:
    pretty_json = json.dumps(obj, indent=4)
    print(pretty_json)


def process():
    logger.info("Process started")
    orchestrator : PipelineOrchestrator = get_pipeline_orchestrator()
    result : PipelineResult = orchestrator.run(get_file())
    print_json(result.document)


if __name__ == '__main__':
    process()
