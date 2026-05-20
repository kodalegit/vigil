"""Import Google Drive or GCS documents into a Vertex AI RAG Engine corpus.

Example:
    uv run python scripts/import_drive_to_rag.py \
      --project my-project \
      --location us-central1 \
      --corpus projects/my-project/locations/us-central1/ragCorpora/123 \
      --path https://drive.google.com/drive/folders/... \
      --path gs://my-bucket/policies/
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--path", action="append", required=True, dest="paths")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=100)
    parser.add_argument("--max-embedding-requests-per-min", type=int, default=900)
    args = parser.parse_args()

    from vertexai import rag
    import vertexai

    vertexai.init(project=args.project, location=args.location)
    response = rag.import_files(
        corpus_name=args.corpus,
        paths=args.paths,
        transformation_config=rag.TransformationConfig(
            rag.ChunkingConfig(
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        ),
        max_embedding_requests_per_min=args.max_embedding_requests_per_min,
    )
    print(response)


if __name__ == "__main__":
    main()
