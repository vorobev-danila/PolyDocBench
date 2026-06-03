# Architecture

PolyDocBench is built around a modular document-generation and evaluation pipeline.

## Data Flow

```mermaid
flowchart LR
    A[Wikipedia page] --> B[Source parser]
    B --> C[Normalized JSON]
    C --> D[Layout engine]
    D --> E[PDF renderer]
    D --> F[Ground truth exporter]
    E --> G[Scan noise]
    G --> H[Noisy images]
    F --> I[Evaluation]
    H --> J[OCR or model predictions]
    J --> I
    I --> K[Interactive dashboard]
```

## Components

```mermaid
flowchart TB
    subgraph Sources
        S1[WikipediaParser]
    end

    subgraph Document
        M1[Document model]
        M2[Normalization]
    end

    subgraph Layout
        L1[ContentLoader]
        L2[LineBreaker]
        L3[PlacementEngine]
        L4[Templates]
    end

    subgraph Render
        R1[PDFRenderer]
        R2[Text/Image/Formula renderers]
        R3[Debug bbox renderer]
    end

    subgraph GT
        G1[GroundTruthExporter]
        G2[Reading order]
        G3[Validators]
    end

    subgraph Evaluation
        E1[OCR quality]
        E2[Ordering metrics]
        E3[Geometry matching]
        E4[Structure metrics]
        E5[Dashboard reporting]
    end

    S1 --> M1
    M1 --> L1
    L1 --> L2 --> L3 --> R1
    L3 --> G1
    R1 --> R2
    R1 --> R3
    G1 --> G2 --> G3
    G1 --> E1
    G1 --> E2
    G1 --> E3
    G1 --> E4
    E1 --> E5
    E2 --> E5
    E4 --> E5
```

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `polydocbench.sources` | Source adapters, currently Wikipedia parsing |
| `polydocbench.document` | Shared document model and normalization |
| `polydocbench.layout` | Line breaking, typography, placement, templates |
| `polydocbench.render` | PDF rendering and debug overlays |
| `polydocbench.gt` | Ground-truth export, schema, validation, reading order |
| `polydocbench.noise` | PDF-to-image conversion and scan noise profiles |
| `polydocbench.eval` | Tesseract quality, semantic-block ordering, Docling structure evaluation, matching, dashboard reporting |
| `polydocbench.api` | FastAPI workflows over the pipeline |
