"""Script to generate synthetic scientific paper fixtures (PDF and DOCX) for CiteVerify.

All fixtures are synthetic, open-domain, and legally unencumbered.
"""

import json
import os
import struct
import zlib
import zipfile
from pathlib import Path


class MinimalPDFBuilder:
    """Constructs valid standard PDF 1.4 documents without third-party dependencies."""

    def __init__(self):
        self.objects = []

    def _add_object(self, content: bytes) -> int:
        self.objects.append(content)
        return len(self.objects)

    def build_text_pdf(self, title: str, pages_text: list[list[str]]) -> bytes:
        """Create a multi-page PDF containing text lines."""
        # obj 1: Catalog
        # obj 2: Font F1 (Helvetica)
        # obj 3: Font F2 (Helvetica-Bold)
        # Pages object and individual page objects are added dynamically.
        catalog_id = 1
        font_f1_id = 2
        font_f2_id = 3

        # We will collect objects and resolve cross-references at the end
        raw_objs = {}
        raw_objs[catalog_id] = b"<< /Type /Catalog /Pages 4 0 R >>"
        raw_objs[font_f1_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        raw_objs[font_f2_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

        pages_obj_id = 4
        current_id = 5

        page_ids = []
        content_ids = []

        for page_lines in pages_text:
            p_id = current_id
            c_id = current_id + 1
            current_id += 2

            page_ids.append(p_id)
            content_ids.append(c_id)

            # Build content stream
            stream_parts = ["BT"]
            y = 750
            for line in page_lines:
                if line.startswith("# "):
                    # Title / Heading 1
                    text = line[2:].replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    stream_parts.append(f"/F2 14 Tf 50 {y} Td ({text}) Tj")
                    y -= 22
                elif line.startswith("## "):
                    # Heading 2
                    text = line[3:].replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    stream_parts.append(f"/F2 11 Tf 50 {y} Td ({text}) Tj")
                    y -= 16
                elif line.startswith("TABLE: "):
                    # Table row representation
                    text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    stream_parts.append(f"/F1 9 Tf 50 {y} Td ({text}) Tj")
                    y -= 13
                else:
                    # Normal body text
                    text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    stream_parts.append(f"/F1 10 Tf 50 {y} Td ({text}) Tj")
                    y -= 14

                if y < 50:
                    y = 750

            stream_parts.append("ET")
            stream_bytes = "\n".join(stream_parts).encode("latin-1", errors="replace")
            content_dict = f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream"
            raw_objs[c_id] = content_dict

            page_dict = (
                f"<< /Type /Page /Parent {pages_obj_id} 0 R "
                f"/MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_f1_id} 0 R /F2 {font_f2_id} 0 R >> >> "
                f"/Contents {c_id} 0 R >>"
            ).encode("latin-1")
            raw_objs[p_id] = page_dict

        kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
        raw_objs[pages_obj_id] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >>".encode("latin-1")

        # Now serialize PDF
        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}

        total_objs = max(raw_objs.keys())
        for obj_idx in range(1, total_objs + 1):
            offsets[obj_idx] = len(out)
            out.extend(f"{obj_idx} 0 obj\n".encode("latin-1"))
            out.extend(raw_objs[obj_idx])
            out.extend(b"\nendobj\n")

        xref_offset = len(out)
        out.extend(f"xref\n0 {total_objs + 1}\n".encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for obj_idx in range(1, total_objs + 1):
            out.extend(f"{offsets[obj_idx]:010d} 00000 n \n".encode("latin-1"))

        out.extend(
            f"trailer\n<< /Size {total_objs + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
                "latin-1"
            )
        )
        return bytes(out)

    def build_scanned_image_pdf(self, width: int = 200, height: int = 260) -> bytes:
        """Create a scanned image-only PDF containing raster image data and zero text operators."""
        # Generate simulated grayscale noise/scan lines image
        raw_pixels = bytearray()
        for row in range(height):
            for col in range(width):
                # Gradient paper texture with simulated scan noise
                base = 240 + ((row * 7 + col * 13) % 15)
                # Draw simulated dark text-like bands
                if (row % 16 in (6, 7, 8)) and (20 < col < 180):
                    val = 40 + ((col * 31) % 60)
                else:
                    val = base
                raw_pixels.append(val)

        compressed_img = zlib.compress(bytes(raw_pixels))

        raw_objs = {}
        raw_objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        raw_objs[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"

        # Image XObject (obj 4)
        raw_objs[4] = (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(compressed_img)} >>\nstream\n".encode("latin-1")
            + compressed_img
            + b"\nendstream"
        )

        # Content stream (obj 5) paints the image across the page: q 512 0 0 692 50 50 cm /Im0 Do Q
        c_bytes = b"q 512 0 0 692 50 50 cm /Im0 Do Q"
        raw_objs[5] = f"<< /Length {len(c_bytes)} >>\nstream\n{c_bytes.decode('latin-1')}\nendstream".encode("latin-1")

        # Page (obj 3) referencing Image XObject in Resources
        raw_objs[3] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"

        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        total_objs = 5
        for obj_idx in range(1, total_objs + 1):
            offsets[obj_idx] = len(out)
            out.extend(f"{obj_idx} 0 obj\n".encode("latin-1"))
            out.extend(raw_objs[obj_idx])
            out.extend(b"\nendobj\n")

        xref_offset = len(out)
        out.extend(f"xref\n0 {total_objs + 1}\n0000000000 65535 f \n".encode("latin-1"))
        for obj_idx in range(1, total_objs + 1):
            out.extend(f"{offsets[obj_idx]:010d} 00000 n \n".encode("latin-1"))

        out.extend(f"trailer\n<< /Size {total_objs + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin-1"))
        return bytes(out)


class MinimalDOCXBuilder:
    """Builds valid Microsoft Word (.docx) files using standard OpenXML and zipfile."""

    @staticmethod
    def build_docx(title: str, paragraphs: list[tuple[str, str]], table_data: list[list[str]] = None) -> bytes:
        """Create a DOCX binary. paragraphs is a list of (style, text)."""
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

        doc_xml_parts = [
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>"""
        ]

        # Add Title
        doc_xml_parts.append(
            f"""    <w:p>
      <w:pPr><w:pStyle w:val="Title"/></w:pPr>
      <w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>{title}</w:t></w:r>
    </w:p>"""
        )

        for style, text in paragraphs:
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if style == "Heading1":
                doc_xml_parts.append(
                    f"""    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t>{escaped}</w:t></w:r>
    </w:p>"""
                )
            elif style == "Heading2":
                doc_xml_parts.append(
                    f"""    <w:p>
      <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
      <w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:t>{escaped}</w:t></w:r>
    </w:p>"""
                )
            else:
                doc_xml_parts.append(
                    f"""    <w:p>
      <w:r><w:t>{escaped}</w:t></w:r>
    </w:p>"""
                )

        if table_data:
            doc_xml_parts.append("    <w:tbl>")
            for row in table_data:
                doc_xml_parts.append("      <w:tr>")
                for cell in row:
                    c_esc = cell.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    doc_xml_parts.append(f"""        <w:tc>
          <w:p><w:r><w:t>{c_esc}</w:t></w:r></w:p>
        </w:tc>""")
                doc_xml_parts.append("      </w:tr>")
            doc_xml_parts.append("    </w:tbl>")

        doc_xml_parts.append("""    <w:sectPr/>
  </w:body>
</w:document>""")

        doc_xml = "\n".join(doc_xml_parts)

        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", doc_xml)

        return buf.getvalue()


def generate_all_fixtures(output_dir: Path):
    """Generate all 10 fixture documents and their metadata manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_builder = MinimalPDFBuilder()
    docx_builder = MinimalDOCXBuilder()

    manifest = {"fixtures": []}

    # -------------------------------------------------------------
    # 1. Numeric Citations PDF
    # -------------------------------------------------------------
    f1_path = output_dir / "fixture_01_numeric_citations.pdf"
    f1_pages = [
        [
            "# Scalable Fault-Tolerant Quantum Surface Codes with Low Overhead",
            "## Abstract",
            "Surface codes offer a promising route to scalable quantum computing. Here we demonstrate a logical error rate reduction using adaptive syndrome decoding [1].",
            "## Introduction",
            "Quantum error correction preserves logical qubits against decoherence [2]. Recent topological architectures achieve fault tolerance below a physical error rate of 1 percent [1], [3].",
            "Syndrome measurement schedules must minimize crosstalk [4]. Our architecture reduces physical qubit overhead by 34 percent compared to standard planar layouts [1].",
            "## Methods",
            "We simulated a rotated surface code lattice with code distances d = 3, 5, and 7 using minimum-weight perfect matching decoders [3].",
            "## Results",
            "Logical error suppression scales exponentially with code distance d when physical error is 0.001 [2]. Threshold analysis confirms stability across 1000 syndrome cycles [4].",
            "## References",
            "[1] Fowler, A. G., et al. (2012). Surface codes: Towards practical large-scale quantum computation. Physical Review A, 86(3), 032324. DOI: 10.1103/PhysRevA.86.032324",
            "[2] Shor, P. W. (1995). Scheme for reducing decoherence in quantum computer memory. Physical Review A, 52(4), R2493. DOI: 10.1103/PhysRevA.52.R2493",
            "[3] Dennis, E., et al. (2002). Topological quantum memory. Journal of Mathematical Physics, 43(9), 4452-4505. DOI: 10.1063/1.1499754",
            "[4] Bravyi, S., and Kitaev, A. (1998). Quantum codes on a lattice with boundary. arXiv:quant-ph/9811052. DOI: 10.48550/arXiv.quant-ph.9811052",
        ]
    ]
    f1_path.write_bytes(pdf_builder.build_text_pdf("Scalable Fault-Tolerant Quantum Surface Codes", f1_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-01",
        "file_name": "fixture_01_numeric_citations.pdf",
        "format": "pdf",
        "title": "Scalable Fault-Tolerant Quantum Surface Codes with Low Overhead",
        "primary_features": ["numeric_citations", "standard_sections"],
        "expected_sections": ["Abstract", "Introduction", "Methods", "Results", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1103/PhysRevA.86.032324", "year": 2012, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1103/PhysRevA.52.R2493", "year": 1995, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[3]", "doi": "10.1063/1.1499754", "year": 2002, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[4]", "doi": "10.48550/arXiv.quant-ph.9811052", "year": 1998, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[1]", "claim_text": "Our architecture reduces physical qubit overhead by 34 percent compared to standard planar layouts.", "section": "Introduction"},
            {"citation_key": "[2]", "claim_text": "Logical error suppression scales exponentially with code distance d when physical error is 0.001.", "section": "Results"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # -------------------------------------------------------------
    # 2. Author-Year Citations PDF
    # -------------------------------------------------------------
    f2_path = output_dir / "fixture_02_author_year_citations.pdf"
    f2_pages = [
        [
            "# Synaptic Pruning Mechanisms in Cortical Development and Neurodegeneration",
            "## Abstract",
            "Microglial phagocytosis regulates synaptic density during postnatal maturation (Stevens et al., 2007). In neurodegenerative models, aberrant reactivation of classical complement cascades triggers premature synapse loss (Hong et al., 2016).",
            "## Introduction",
            "Synaptic elimination is essential for refining neural circuitry (Stevens et al., 2007). C1q localizes selectively to immature synapses prior to microglial engulfment (Bialas and Stevens, 2013).",
            "In murine models of Alzheimer's disease, inhibiting C1q preserves synaptic density and cognitive function (Hong et al., 2016). High-resolution in vivo imaging confirms that microglial-synapse contact duration predicts elimination (Paolicelli et al., 2011).",
            "## Discussion",
            "These findings establish complement-mediated tagging as a conserved mechanism (Stevens et al., 2007; Hong et al., 2016). Therapeutic modulation of microglial receptors may prevent early cognitive decline (Paolicelli et al., 2011).",
            "## References",
            "Bialas, A. R., and Stevens, B. (2013). TGF-beta signaling regulates neuronal C1q expression. Nature Neuroscience, 16(12), 1773-1782. DOI: 10.1038/nn.3560",
            "Hong, S., et al. (2016). Complement and microglia mediate early synapse loss in Alzheimer mouse models. Science, 352(6286), 712-716. DOI: 10.1126/science.aad8373",
            "Paolicelli, R. C., et al. (2011). Synaptic pruning by microglia is necessary for normal brain development. Science, 333(6048), 1456-1458. DOI: 10.1126/science.1202529",
            "Stevens, B., et al. (2007). The classical complement cascade mediates CNS synapse elimination. Cell, 131(6), 1164-1178. DOI: 10.1016/j.cell.2007.10.036",
        ]
    ]
    f2_path.write_bytes(pdf_builder.build_text_pdf("Synaptic Pruning Mechanisms", f2_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-02",
        "file_name": "fixture_02_author_year_citations.pdf",
        "format": "pdf",
        "title": "Synaptic Pruning Mechanisms in Cortical Development and Neurodegeneration",
        "primary_features": ["author_year_citations", "multi_author_parenthetical"],
        "expected_sections": ["Abstract", "Introduction", "Discussion", "References"],
        "expected_references": [
            {"citation_key": "(Bialas and Stevens, 2013)", "doi": "10.1038/nn.3560", "year": 2013, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "(Hong et al., 2016)", "doi": "10.1126/science.aad8373", "year": 2016, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "(Paolicelli et al., 2011)", "doi": "10.1126/science.1202529", "year": 2011, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "(Stevens et al., 2007)", "doi": "10.1016/j.cell.2007.10.036", "year": 2007, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "(Hong et al., 2016)", "claim_text": "In murine models of Alzheimer's disease, inhibiting C1q preserves synaptic density and cognitive function.", "section": "Introduction"},
            {"citation_key": "(Stevens et al., 2007)", "claim_text": "C1q localizes selectively to immature synapses prior to microglial engulfment.", "section": "Introduction"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # -------------------------------------------------------------
    # 3. Missing References PDF
    # -------------------------------------------------------------
    f3_path = output_dir / "fixture_03_missing_references.pdf"
    f3_pages = [
        [
            "# Targeted Kinase Inhibition in Metastatic Adenocarcinoma",
            "## Abstract",
            "Receptor tyrosine kinase mutations drive resistance to first-line therapies [1]. We evaluate allosteric inhibitors in patient-derived xenografts [2].",
            "## Results",
            "Prior studies established that secondary EGFR mutations cause resistance in 48 percent of non-small cell lung carcinomas [3].",
            "Combination therapy with compound CV-88 suppressed tumor growth by 72 percent without dose-limiting hepatotoxicity [4].",
            "Unexpectedly, concurrent down-regulation of MET amplification was observed across all responders [5].",
            "## References",
            "[1] Lynch, T. J., et al. (2004). Activating mutations in EGFR underlying responsiveness of NSCLC to gefitinib. NEJM, 350(21), 2129-2139. DOI: 10.1056/NEJMoa040938",
            "[2] Pao, W., et al. (2005). Acquired resistance of lung adenocarcinomas to gefitinib or erlotinib is associated with a second mutation in the EGFR kinase domain. PLoS Med, 2(3), e73. DOI: 10.1371/journal.pmed.0020073",
            "[4] Sequist, L. V., et al. (2011). Genotypic and histological evolution of lung cancers acquiring resistance to EGFR inhibitors. Science TM, 3(75), 75ra26. DOI: 10.1126/scitranslmed.3002003",
        ]
    ]
    f3_path.write_bytes(pdf_builder.build_text_pdf("Targeted Kinase Inhibition", f3_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-03",
        "file_name": "fixture_03_missing_references.pdf",
        "format": "pdf",
        "title": "Targeted Kinase Inhibition in Metastatic Adenocarcinoma",
        "primary_features": ["missing_references", "dangling_in_text_citations"],
        "expected_sections": ["Abstract", "Results", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1056/NEJMoa040938", "year": 2004, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1371/journal.pmed.0020073", "year": 2005, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[4]", "doi": "10.1126/scitranslmed.3002003", "year": 2011, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[3]", "claim_text": "Prior studies established that secondary EGFR mutations cause resistance in 48 percent of non-small cell lung carcinomas.", "section": "Results"},
            {"citation_key": "[5]", "claim_text": "Unexpectedly, concurrent down-regulation of MET amplification was observed across all responders.", "section": "Results"},
        ],
        "expected_anomalies": {
            "missing_references": ["[3]", "[5]"],
            "duplicate_dois": [],
            "malformed_references": [],
            "scanned_image_only": False,
        },
    })

    # -------------------------------------------------------------
    # 4. Duplicate DOIs PDF
    # -------------------------------------------------------------
    f4_path = output_dir / "fixture_04_duplicate_dois.pdf"
    f4_pages = [
        [
            "# High-Throughput Somatic Variant Calling Across Longitudinal Cohorts",
            "## Abstract",
            "Accurate variant calling in low-coverage whole-genome sequencing requires calibrated indel realignment [1]. Benchmarking pipelines reveals substantial cross-platform discrepancy [2].",
            "## Introduction",
            "Deep sequencing enables sensitive subclonal reconstruction [3]. Filtering artifactual calls using panel-of-normals reduces false positive rates [4].",
            "## References",
            "[1] McKenna, A., et al. (2010). The Genome Analysis Toolkit: a MapReduce framework for analyzing next-generation DNA sequencing data. Genome Research, 20(9), 1297-1303. DOI: 10.1038/s41586-020-2649-2",
            "[2] Li, H., and Durbin, R. (2009). Fast and accurate short read alignment with Burrows-Wheeler transform. Bioinformatics, 25(14), 1754-1760. DOI: 10.1093/bioinformatics/btp324",
            "[3] McKenna, A., and Depristo, M. (2010). Variant Discovery in Massive NextGen Datasets. Genome Res, 20, 1297. DOI: 10.1038/s41586-020-2649-2",
            "[4] Li, H., and Durbin, R. (2009). Fast and accurate short read alignment with Burrows-Wheeler transform. Bioinformatics, 25(14), 1754-1760. DOI: 10.1093/bioinformatics/btp324",
        ]
    ]
    f4_path.write_bytes(pdf_builder.build_text_pdf("High-Throughput Somatic Variant Calling", f4_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-04",
        "file_name": "fixture_04_duplicate_dois.pdf",
        "format": "pdf",
        "title": "High-Throughput Somatic Variant Calling Across Longitudinal Cohorts",
        "primary_features": ["duplicate_dois", "duplicate_references"],
        "expected_sections": ["Abstract", "Introduction", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1038/s41586-020-2649-2", "year": 2010, "is_malformed": False, "is_duplicate": True, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1093/bioinformatics/btp324", "year": 2009, "is_malformed": False, "is_duplicate": True, "is_missing": False},
            {"citation_key": "[3]", "doi": "10.1038/s41586-020-2649-2", "year": 2010, "is_malformed": False, "is_duplicate": True, "is_missing": False},
            {"citation_key": "[4]", "doi": "10.1093/bioinformatics/btp324", "year": 2009, "is_malformed": False, "is_duplicate": True, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[1]", "claim_text": "Accurate variant calling in low-coverage whole-genome sequencing requires calibrated indel realignment.", "section": "Abstract"},
            {"citation_key": "[3]", "claim_text": "Deep sequencing enables sensitive subclonal reconstruction.", "section": "Introduction"},
        ],
        "expected_anomalies": {
            "missing_references": [],
            "duplicate_dois": ["10.1038/s41586-020-2649-2", "10.1093/bioinformatics/btp324"],
            "malformed_references": [],
            "scanned_image_only": False,
        },
    })

    # -------------------------------------------------------------
    # 5. Malformed References PDF
    # -------------------------------------------------------------
    f5_path = output_dir / "fixture_05_malformed_references.pdf"
    f5_pages = [
        [
            "# Nonlinear Ocean Circulation Feedbacks Under Global Warming Scenarios",
            "## Abstract",
            "Thermohaline circulation collapse exhibits bistability in coupled general circulation models [1]. Freshening of the North Atlantic suppresses deep convection [2].",
            "## Results",
            "Under an RCP 8.5 greenhouse emission projection, Atlantic meridional overturning circulation decreases by 38 percent by 2100 [3], [4].",
            "## References",
            "[1] Stommel, H. (1961). Thermohaline convection with two stable regimes of flow. Tellus, 13(2), 224-230. DOI: 10.3402/tellusa.v13i2.9491",
            "[2] Rahmstorf, S. Rapid climate change in the North Atlantic. DOI: 10.5555/invalid_doi_syntax#bad_url",
            "[3] (Unclosed author bracket: Broecker, W. S. The great ocean conveyor. Oceanography, 4(2), 79-89.",
            "[4] Manabe, S., and Stouffer, R. J. Simulation of abrupt climate change induced by freshwater input. (Missing venue and year)",
        ]
    ]
    f5_path.write_bytes(pdf_builder.build_text_pdf("Nonlinear Ocean Circulation Feedbacks", f5_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-05",
        "file_name": "fixture_05_malformed_references.pdf",
        "format": "pdf",
        "title": "Nonlinear Ocean Circulation Feedbacks Under Global Warming Scenarios",
        "primary_features": ["malformed_references", "invalid_doi_syntax", "missing_bibliographic_metadata"],
        "expected_sections": ["Abstract", "Results", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.3402/tellusa.v13i2.9491", "year": 1961, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.5555/invalid_doi_syntax#bad_url", "year": None, "is_malformed": True, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[3]", "doi": None, "year": None, "is_malformed": True, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[4]", "doi": None, "year": None, "is_malformed": True, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[2]", "claim_text": "Freshening of the North Atlantic suppresses deep convection.", "section": "Abstract"},
            {"citation_key": "[3]", "claim_text": "Under an RCP 8.5 greenhouse emission projection, Atlantic meridional overturning circulation decreases by 38 percent by 2100.", "section": "Results"},
        ],
        "expected_anomalies": {
            "missing_references": [],
            "duplicate_dois": [],
            "malformed_references": ["[2]", "[3]", "[4]"],
            "scanned_image_only": False,
        },
    })

    # -------------------------------------------------------------
    # 6. Tables PDF
    # -------------------------------------------------------------
    f6_path = output_dir / "fixture_06_tables.pdf"
    f6_pages = [
        [
            "# Atmospheric Characterization and Transmission Spectroscopy of Warm Neptunes",
            "## Abstract",
            "Transmission spectroscopy of transiting exoplanets reveals water vapor absorption bands [1].",
            "## Observational Results",
            "Table 1 summarizes atmospheric scale heights and observed H2O feature amplitudes across target planets.",
            "TABLE: Target Name   | Period (d) | Mass (M_J) | Scale Height (km) | Baseline Source",
            "TABLE: HAT-P-11b     | 4.887      | 0.081      | 210               | Fraine et al. [1]",
            "TABLE: GJ-436b       | 2.643      | 0.070      | 145               | Knutson et al. [2]",
            "TABLE: WASP-107b     | 5.721      | 0.096      | 930               | Spake et al. [3]",
            "As indicated in Table 1, WASP-107b exhibits an anomalously high scale height of 930 km due to its low mean molecular weight [3].",
            "In contrast, HAT-P-11b displays clear water absorption features corresponding to 3.2 scale heights [1].",
            "## References",
            "[1] Fraine, J., et al. (2014). Water vapour defense in the atmosphere of the warm Neptune HAT-P-11b. Nature, 513(7519), 526-529. DOI: 10.1038/nature13785",
            "[2] Knutson, H. A., et al. (2014). A featureless transmission spectrum for the Neptune-mass exoplanet GJ 436b. Nature, 505(7481), 66-68. DOI: 10.1038/nature12887",
            "[3] Spake, J. J., et al. (2018). Helium in the eroding atmosphere of an exoplanet. Nature, 557(7703), 68-70. DOI: 10.1038/s41586-018-0067-3",
        ]
    ]
    f6_path.write_bytes(pdf_builder.build_text_pdf("Atmospheric Characterization of Warm Neptunes", f6_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-06",
        "file_name": "fixture_06_tables.pdf",
        "format": "pdf",
        "title": "Atmospheric Characterization and Transmission Spectroscopy of Warm Neptunes",
        "primary_features": ["tables", "table_cell_citations", "tabular_data_claims"],
        "expected_sections": ["Abstract", "Observational Results", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1038/nature13785", "year": 2014, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1038/nature12887", "year": 2014, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[3]", "doi": "10.1038/s41586-018-0067-3", "year": 2018, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[3]", "claim_text": "WASP-107b exhibits an anomalously high scale height of 930 km due to its low mean molecular weight.", "section": "Observational Results"},
            {"citation_key": "[1]", "claim_text": "HAT-P-11b displays clear water absorption features corresponding to 3.2 scale heights.", "section": "Observational Results"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # -------------------------------------------------------------
    # 7. Scientific Notation PDF
    # -------------------------------------------------------------
    f7_path = output_dir / "fixture_07_scientific_notation.pdf"
    f7_pages = [
        [
            "# Ballistic Carrier Transport in Low-Dimensional Transition Metal Dichalcogenides",
            "## Abstract",
            "Monolayer WS2 flakes demonstrate high room-temperature electron mobilities exceeding 1.2 x 10^3 cm^2 V^-1 s^-1 [1].",
            "## Physical Characteristics",
            "The fundamental charge quantum is e = 1.602 x 10^-19 C and electron rest mass is m_e = 9.109 x 10^-31 kg [2].",
            "Carrier sheet density reached n_s = 4.85 x 10^12 cm^-2 at a gate bias of V_g = +2.5 V [1].",
            "Phonon scattering lifetime was measured as tau = 2.45 x 10^-13 s at T = 300 K [1].",
            "Optical bandgap transitions occur at photon energies of 3.28 x 10^-19 J (2.05 eV) under vacuum dielectric constant epsilon_0 = 8.854 x 10^-12 F/m [2].",
            "## References",
            "[1] Radisavljevic, B., et al. (2011). Single-layer MoS2 transistors. Nature Nanotechnology, 6(3), 147-150. DOI: 10.1038/nnano.2010.279",
            "[2] Novoselov, K. S., et al. (2005). Two-dimensional gas of massless Dirac fermions in graphene. Nature, 438(7065), 197-200. DOI: 10.1038/nature04233",
        ]
    ]
    f7_path.write_bytes(pdf_builder.build_text_pdf("Ballistic Carrier Transport", f7_pages))

    manifest["fixtures"].append({
        "fixture_id": "FIX-07",
        "file_name": "fixture_07_scientific_notation.pdf",
        "format": "pdf",
        "title": "Ballistic Carrier Transport in Low-Dimensional Transition Metal Dichalcogenides",
        "primary_features": ["scientific_notation", "exponents_and_units", "physical_constants"],
        "expected_sections": ["Abstract", "Physical Characteristics", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1038/nnano.2010.279", "year": 2011, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1038/nature04233", "year": 2005, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[1]", "claim_text": "Carrier sheet density reached n_s = 4.85 x 10^12 cm^-2 at a gate bias of V_g = +2.5 V.", "section": "Physical Characteristics"},
            {"citation_key": "[1]", "claim_text": "Phonon scattering lifetime was measured as tau = 2.45 x 10^-13 s at T = 300 K.", "section": "Physical Characteristics"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # -------------------------------------------------------------
    # 8. Scanned / Image-Only PDF
    # -------------------------------------------------------------
    f8_path = output_dir / "fixture_08_scanned_image_only.pdf"
    f8_path.write_bytes(pdf_builder.build_scanned_image_pdf(width=220, height=280))

    manifest["fixtures"].append({
        "fixture_id": "FIX-08",
        "file_name": "fixture_08_scanned_image_only.pdf",
        "format": "pdf",
        "title": "Foundational Cybernetics and Information Feedback Loops (1954 Scanned Archive)",
        "primary_features": ["scanned_image_only", "zero_text_stream", "ocr_fallback_required"],
        "expected_sections": [],
        "expected_references": [],
        "expected_claims": [],
        "expected_anomalies": {
            "missing_references": [],
            "duplicate_dois": [],
            "malformed_references": [],
            "scanned_image_only": True,
            "ocr_required": True,
        },
    })

    # -------------------------------------------------------------
    # 9. Tables and Metadata DOCX
    # -------------------------------------------------------------
    f9_path = output_dir / "fixture_09_tables_and_metadata.docx"
    f9_paragraphs = [
        ("Heading1", "Abstract"),
        ("Normal", "Lipid nanoparticle (LNP) formulations mediate efficient mRNA delivery in vivo [1]. Here we evaluate ionizable lipid formulations for spleen vs liver tropism [2]."),
        ("Heading1", "Formulation Benchmarking"),
        ("Normal", "Table 1 compares encapsulation efficiency and pKa values across three tested formulations."),
        ("Normal", "Formulation LNP-03 demonstrated 94.2 percent encapsulation efficiency with high splenic delivery selectivity [2]."),
        ("Heading1", "References"),
        ("Normal", "[1] Pardi, N., et al. (2018). mRNA vaccines - a new era in vaccinology. Nature Reviews Drug Discovery, 17(4), 261-279. DOI: 10.1038/nrd.2017.243"),
        ("Normal", "[2] Akinc, A., et al. (2019). The Onpattro story and the clinical translation of nanomedicines. Nature Nanotechnology, 14(12), 1084-1087. DOI: 10.1038/s41565-019-0591-y"),
    ]
    f9_table = [
        ["Formulation ID", "Ionizable Lipid", "pKa", "Encapsulation (%)", "Reference"],
        ["LNP-01", "DLin-MC3-DMA", "6.44", "88.5", "Pardi et al. [1]"],
        ["LNP-02", "ALC-0315", "6.09", "91.2", "Akinc et al. [2]"],
        ["LNP-03", "SM-102", "6.68", "94.2", "Akinc et al. [2]"],
    ]
    f9_path.write_bytes(docx_builder.build_docx("Comparative Benchmarking of mRNA Delivery Formulations", f9_paragraphs, f9_table))

    manifest["fixtures"].append({
        "fixture_id": "FIX-09",
        "file_name": "fixture_09_tables_and_metadata.docx",
        "format": "docx",
        "title": "Comparative Benchmarking of mRNA Delivery Formulations",
        "primary_features": ["docx_format", "tables", "numeric_citations"],
        "expected_sections": ["Abstract", "Formulation Benchmarking", "References"],
        "expected_references": [
            {"citation_key": "[1]", "doi": "10.1038/nrd.2017.243", "year": 2018, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "[2]", "doi": "10.1038/s41565-019-0591-y", "year": 2019, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "[2]", "claim_text": "Formulation LNP-03 demonstrated 94.2 percent encapsulation efficiency with high splenic delivery selectivity.", "section": "Formulation Benchmarking"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # -------------------------------------------------------------
    # 10. Author-Year Multi-Section DOCX
    # -------------------------------------------------------------
    f10_path = output_dir / "fixture_10_author_year_multisection.docx"
    f10_paragraphs = [
        ("Heading1", "Abstract"),
        ("Normal", "Attentional shifting incurs a measurable response time cost during task switching (Monsell, 2003). We assess whether working memory capacity buffers against switch costs (Baddeley, 2000)."),
        ("Heading1", "Introduction"),
        ("Normal", "Executive control allocates cognitive resources across competing goals (Monsell, 2003). Dual-task interference reflects capacity limits of the central executive (Baddeley, 2000; Miyake et al., 2000)."),
        ("Heading1", "Discussion"),
        ("Normal", "Our empirical results corroborate that latent working memory capacity reduces switch latency by 28 milliseconds (Miyake et al., 2000)."),
        ("Heading1", "References"),
        ("Normal", "Baddeley, A. (2000). The episodic buffer: a new component of working memory? Trends in Cognitive Sciences, 4(11), 417-423. DOI: 10.1016/S1364-6613(00)01538-2"),
        ("Normal", "Miyake, A., et al. (2000). The unity and diversity of executive functions. Cognitive Psychology, 41(1), 49-100. DOI: 10.1006/cogp.1999.0734"),
        ("Normal", "Monsell, S. (2003). Task switching. Trends in Cognitive Sciences, 7(3), 134-140. DOI: 10.1016/S1364-6613(03)00028-7"),
    ]
    f10_path.write_bytes(docx_builder.build_docx("Cognitive Load and Attentional Shifting in Multitasking Environments", f10_paragraphs))

    manifest["fixtures"].append({
        "fixture_id": "FIX-10",
        "file_name": "fixture_10_author_year_multisection.docx",
        "format": "docx",
        "title": "Cognitive Load and Attentional Shifting in Multitasking Environments",
        "primary_features": ["docx_format", "author_year_citations", "multisection"],
        "expected_sections": ["Abstract", "Introduction", "Discussion", "References"],
        "expected_references": [
            {"citation_key": "(Baddeley, 2000)", "doi": "10.1016/S1364-6613(00)01538-2", "year": 2000, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "(Miyake et al., 2000)", "doi": "10.1006/cogp.1999.0734", "year": 2000, "is_malformed": False, "is_duplicate": False, "is_missing": False},
            {"citation_key": "(Monsell, 2003)", "doi": "10.1016/S1364-6613(03)00028-7", "year": 2003, "is_malformed": False, "is_duplicate": False, "is_missing": False},
        ],
        "expected_claims": [
            {"citation_key": "(Miyake et al., 2000)", "claim_text": "Our empirical results corroborate that latent working memory capacity reduces switch latency by 28 milliseconds.", "section": "Discussion"},
        ],
        "expected_anomalies": {"missing_references": [], "duplicate_dois": [], "malformed_references": [], "scanned_image_only": False},
    })

    # Write Manifest
    manifest_path = output_dir.parent / "fixtures_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Successfully generated {len(manifest['fixtures'])} fixtures and saved manifest to {manifest_path}")


if __name__ == "__main__":
    generate_all_fixtures(Path(__file__).parent / "documents")
