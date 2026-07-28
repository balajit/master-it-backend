"""Generate a rich test PDF for ContentNode integration testing.

Produces test_pdfs/content_node_test.pdf with:
- Multiple headings (H1, H2, H3)
- Paragraphs of plain text
- A bullet list
- A numbered list
- A block equation
- A code block
- A table
- An image/figure
- Bold and italic inline text
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).resolve().parent / "content_node_test.pdf"


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Chapter heading (H1) ──────────────────────────────────────────────
    story.append(
        Paragraph("Chapter 1: Fundamentals of Mathematics", styles["Heading1"])
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Section heading (H2) ─────────────────────────────────────────────
    story.append(Paragraph("1.1 Introduction", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))

    # ── Plain paragraph ───────────────────────────────────────────────────
    story.append(
        Paragraph(
            "Mathematics is the study of numbers, quantities, shapes, and patterns. "
            "It provides the language and tools needed to describe the physical world "
            "precisely and rigorously. From counting apples to launching satellites, "
            "mathematics underpins every scientific discipline.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Inline bold/italic paragraph ─────────────────────────────────────
    story.append(
        Paragraph(
            "The <b>fundamental theorem of calculus</b> connects differentiation and "
            "integration. It states that if <i>f</i> is continuous on [a, b] then the "
            "function F defined by F(x) = integral from a to x of f(t) dt is differentiable "
            "and F'(x) = f(x).",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Subsection heading (H3) ───────────────────────────────────────────
    story.append(Paragraph("1.1.1 Key Definitions", styles["Heading3"]))
    story.append(Spacer(1, 0.05 * inch))

    # ── Definition-style paragraph ────────────────────────────────────────
    story.append(
        Paragraph(
            "<b>Derivative:</b> The derivative of a function f at a point x is defined as "
            "the limit of (f(x+h) - f(x)) / h as h approaches zero, provided the limit exists.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        Paragraph(
            "<b>Integral:</b> The definite integral of f over [a, b] represents the net "
            "signed area between the curve y = f(x) and the x-axis over that interval.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Section heading (H2) ─────────────────────────────────────────────
    story.append(Paragraph("1.2 Algebraic Foundations", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))

    # ── Bullet list ───────────────────────────────────────────────────────
    story.append(Paragraph("Core algebraic properties:", styles["Normal"]))
    story.append(Spacer(1, 0.05 * inch))
    bullet_items = [
        "Commutative property: a + b = b + a",
        "Associative property: (a + b) + c = a + (b + c)",
        "Distributive property: a * (b + c) = a*b + a*c",
        "Identity element: a + 0 = a",
        "Inverse element: a + (-a) = 0",
    ]
    story.append(
        ListFlowable(
            [
                ListItem(Paragraph(item, styles["Normal"]), bulletText="•")
                for item in bullet_items
            ],
            bulletType="bullet",
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Numbered list ─────────────────────────────────────────────────────
    story.append(
        Paragraph(
            "Steps to solve a quadratic equation ax^2 + bx + c = 0:", styles["Normal"]
        )
    )
    story.append(Spacer(1, 0.05 * inch))
    numbered_items = [
        "Identify the coefficients a, b, and c.",
        "Compute the discriminant D = b^2 - 4ac.",
        "If D >= 0, apply the quadratic formula: x = (-b ± sqrt(D)) / (2a).",
        "If D < 0, the roots are complex conjugates.",
    ]
    story.append(
        ListFlowable(
            [ListItem(Paragraph(item, styles["Normal"])) for item in numbered_items],
            bulletType="1",
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Block equation (rendered as a styled paragraph) ───────────────────
    story.append(Paragraph("1.3 Important Equations", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))

    eq_style = ParagraphStyle(
        "Equation",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=13,
        leftIndent=40,
        spaceAfter=6,
        spaceBefore=6,
        backColor=colors.HexColor("#f5f5f5"),
    )

    story.append(Paragraph("Quadratic formula:", styles["Normal"]))
    story.append(
        Paragraph("x = (-b ± sqrt(b^2 - 4ac)) / (2a)  ... (Eq. 1.1)", eq_style)
    )
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Euler's identity:", styles["Normal"]))
    story.append(Paragraph("e^(i*pi) + 1 = 0  ... (Eq. 1.2)", eq_style))
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Pythagorean theorem:", styles["Normal"]))
    story.append(Paragraph("a^2 + b^2 = c^2  ... (Eq. 1.3)", eq_style))
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Area of a circle:", styles["Normal"]))
    story.append(Paragraph("A = pi * r^2  ... (Eq. 1.4)", eq_style))
    story.append(Spacer(1, 0.1 * inch))

    # ── Data table ────────────────────────────────────────────────────────
    story.append(Paragraph("1.4 Trigonometric Values", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        Paragraph(
            "The following table shows common trigonometric function values.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.05 * inch))

    table_data = [
        ["Angle (deg)", "sin(θ)", "cos(θ)", "tan(θ)"],
        ["0°", "0", "1", "0"],
        ["30°", "1/2", "√3/2", "1/√3"],
        ["45°", "√2/2", "√2/2", "1"],
        ["60°", "√3/2", "1/2", "√3"],
        ["90°", "1", "0", "undefined"],
    ]
    tbl = Table(table_data, colWidths=[1.3 * inch, 1.3 * inch, 1.3 * inch, 1.3 * inch])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ecf0f1")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#ecf0f1")],
                ),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
            ]
        )
    )
    story.append(tbl)
    story.append(Spacer(1, 0.1 * inch))

    # ── Code block ────────────────────────────────────────────────────────
    story.append(Paragraph("1.5 Numerical Methods", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        Paragraph(
            "The Newton-Raphson method iteratively approximates roots of f(x) = 0 using:",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.05 * inch))

    code_style = ParagraphStyle(
        "Code",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=10,
        leftIndent=40,
        spaceAfter=2,
        spaceBefore=2,
        leading=14,
        backColor=colors.HexColor("#282c34"),
        textColor=colors.HexColor("#abb2bf"),
    )

    code_lines = [
        "def newton_raphson(f, df, x0, tol=1e-6, max_iter=100):",
        "    x = x0",
        "    for i in range(max_iter):",
        "        fx = f(x)",
        "        if abs(fx) < tol:",
        "            return x",
        "        x = x - fx / df(x)",
        "    raise ValueError('Did not converge')",
    ]
    for line in code_lines:
        story.append(Paragraph(line.replace(" ", "&nbsp;"), code_style))
    story.append(Spacer(1, 0.1 * inch))

    # ── Note / tip block ──────────────────────────────────────────────────
    note_style = ParagraphStyle(
        "Note",
        parent=styles["Normal"],
        leftIndent=20,
        rightIndent=20,
        spaceAfter=6,
        spaceBefore=6,
        borderPadding=8,
        backColor=colors.HexColor("#fff3cd"),
        borderColor=colors.HexColor("#ffc107"),
        borderWidth=2,
        borderRadius=4,
    )
    story.append(
        Paragraph(
            "<b>TIP:</b> When implementing Newton-Raphson, always check that df(x) != 0 "
            "to avoid division by zero. Add a guard clause before the division step.",
            note_style,
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    # ── Section heading (H2) + more equations ─────────────────────────────
    story.append(Paragraph("1.6 Calculus Review", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        Paragraph(
            "The derivative of common functions is summarized below. "
            "These rules are applied extensively in optimization problems.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Power rule:", styles["Normal"]))
    story.append(Paragraph("d/dx [x^n] = n * x^(n-1)  ... (Eq. 1.5)", eq_style))
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Chain rule:", styles["Normal"]))
    story.append(
        Paragraph("d/dx [f(g(x))] = f'(g(x)) * g'(x)  ... (Eq. 1.6)", eq_style)
    )
    story.append(Spacer(1, 0.05 * inch))

    story.append(Paragraph("Product rule:", styles["Normal"]))
    story.append(Paragraph("d/dx [u*v] = u'*v + u*v'  ... (Eq. 1.7)", eq_style))
    story.append(Spacer(1, 0.1 * inch))

    # ── Summary paragraph ─────────────────────────────────────────────────
    story.append(Paragraph("1.7 Summary", styles["Heading2"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        Paragraph(
            "In this chapter we reviewed the fundamental building blocks of mathematics: "
            "algebraic properties, key definitions from calculus, important equations, "
            "trigonometric identities, and numerical methods. These concepts form the "
            "backbone of all advanced study in science and engineering.",
            styles["Normal"],
        )
    )

    doc.build(story)
    print(f"Generated: {OUTPUT}")


if __name__ == "__main__":
    build()
