"""Generate BuildBudget AI presentation (up to 14 slides)."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# --- Brand colours ---
NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x5C, 0x8A)
LIGHT_BLUE = RGBColor(0xD9, 0xE6, 0xF2)
GREY = RGBColor(0x59, 0x59, 0x59)
BLACK = RGBColor(0x22, 0x22, 0x22)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT = RGBColor(0x00, 0x7A, 0xC3)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

BLANK = prs.slide_layouts[6]  # blank layout


def add_title_bar(slide, title, subtitle=None):
    """Add a clean navy title bar at the top."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(1.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = NAVY
    bar.line.fill.background()
    tf = bar.text_frame
    tf.text = title
    tf.paragraphs[0].font.size = Pt(28)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = WHITE
    tf.paragraphs[0].alignment = PP_ALIGN.LEFT
    tf.margin_left = Inches(0.6)
    tf.margin_top = Inches(0.15)
    if subtitle:
        p = tf.add_paragraph()
        p.text = subtitle
        p.font.size = Pt(13)
        p.font.color.rgb = RGBColor(0xB0, 0xC4, 0xDE)
        p.font.italic = True
        p.alignment = PP_ALIGN.LEFT


def add_bullets(slide, items, left=0.7, top=1.5, width=11.9, font_size=18, spacing=6):
    """Add a bulleted list."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(5.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        if item.strip() == "":
            p.text = ""
            p.space_after = Pt(2)
            continue
        # Support bold lead-in with "||" separator
        if "||" in item:
            lead, rest = item.split("||", 1)
            p.text = "\u2022  " + lead.strip()
            run = p.runs[0]
            run.bold = True
            run.font.size = Pt(font_size)
            run.font.color.rgb = BLACK
            r2 = p.add_run()
            r2.text = " " + rest.strip()
            r2.font.size = Pt(font_size)
            r2.font.color.rgb = GREY
        else:
            p.text = "\u2022  " + item
            for run in p.runs:
                run.font.size = Pt(font_size)
                run.font.color.rgb = BLACK
        p.space_after = Pt(spacing)
        p.level = 0
    return txBox


def add_two_col(slide, left_items, right_items, left_title=None, right_title=None, top=1.5):
    """Two-column layout with optional column titles."""
    if left_title:
        tb = slide.shapes.add_textbox(Inches(0.7), Inches(top), Inches(5.9), Inches(0.4))
        tf = tb.text_frame
        p = tf.paragraphs[0]
        p.text = left_title
        p.font.bold = True
        p.font.size = Pt(16)
        p.font.color.rgb = BLUE
    if right_title:
        tb = slide.shapes.add_textbox(Inches(7.0), Inches(top), Inches(5.9), Inches(0.4))
        tf = tb.text_frame
        p = tf.paragraphs[0]
        p.text = right_title
        p.font.bold = True
        p.font.size = Pt(16)
        p.font.color.rgb = BLUE
    offset = 0.45 if (left_title or right_title) else 0
    add_bullets(slide, left_items, left=0.7, top=top + offset, width=5.9, font_size=15, spacing=4)
    add_bullets(slide, right_items, left=7.0, top=top + offset, width=5.9, font_size=15, spacing=4)


def add_footer(slide, text="BuildBudget AI  |  Confidential"):
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(7.1), Inches(12.1), Inches(0.3))
    tf = tb.text_frame
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(9)
    p.font.color.rgb = GREY
    p.alignment = PP_ALIGN.CENTER


def new_slide(title, subtitle=None):
    slide = prs.slides.add_slide(BLANK)
    add_title_bar(slide, title, subtitle)
    add_footer(slide)
    return slide


# ============================================================
# SLIDE 1 — Title
# ============================================================
slide = prs.slides.add_slide(BLANK)
# Background accent bar
bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5))
bar.fill.solid()
bar.fill.fore_color.rgb = NAVY
bar.line.fill.background()
# Title
tb = slide.shapes.add_textbox(Inches(1.2), Inches(2.0), Inches(10.9), Inches(1.2))
tf = tb.text_frame
p = tf.paragraphs[0]
p.text = "BuildBudget AI"
p.font.size = Pt(48)
p.font.bold = True
p.font.color.rgb = WHITE
p.alignment = PP_ALIGN.CENTER
# Subtitle
tb2 = slide.shapes.add_textbox(Inches(1.2), Inches(3.3), Inches(10.9), Inches(1.0))
tf2 = tb2.text_frame
p2 = tf2.paragraphs[0]
p2.text = "Agentic AI-Powered Construction Planning, Cost Estimation & Project Management"
p2.font.size = Pt(20)
p2.font.color.rgb = RGBColor(0xB0, 0xC4, 0xDE)
p2.alignment = PP_ALIGN.CENTER
# Divider line
line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.5), Inches(4.6), Inches(4.3), Inches(0.04))
line.fill.solid()
line.fill.fore_color.rgb = ACCENT
line.line.fill.background()
# Bottom info
tb3 = slide.shapes.add_textbox(Inches(1.2), Inches(5.0), Inches(10.9), Inches(1.5))
tf3 = tb3.text_frame
for txt in ["Full-Stack Python  |  FastAPI  |  LangChain  |  LangGraph  |  Hybrid RAG",
            "Generative AI Subject Project  |  2026"]:
    p = tf3.add_paragraph() if tf3.paragraphs[0].text else tf3.paragraphs[0]
    p.text = txt
    p.font.size = Pt(14)
    p.font.color.rgb = RGBColor(0x80, 0x9B, 0xBF)
    p.alignment = PP_ALIGN.CENTER
    p.space_after = Pt(4)

# ============================================================
# SLIDE 2 — Problem Statement
# ============================================================
slide = new_slide("The Problem", "What real-world issue does BuildBudget AI solve?")
add_bullets(slide, [
    "Construction projects are managed using Excel sheets, calculators, paper documents and WhatsApp messages",
    "Material estimation is often wrong, leading to budget overruns",
    "Supplier prices and quotations are hard to compare",
    "Material shortages are discovered too late",
    "Project schedules and task dependencies are not tracked properly",
    "Construction documents are difficult to search and understand",
    "Reports and emails are prepared manually, wasting time",
    "Information is scattered across different tools and applications",
], font_size=17)

# ============================================================
# SLIDE 3 — Project Overview
# ============================================================
slide = new_slide("Project Overview", "Key details at a glance")
add_two_col(slide,
    ["Project name||BuildBudget AI",
     "Domain||Construction Technology (ConTech)",
     "Type||Full-stack Agentic AI application",
     "Backend||FastAPI (Python)",
     "Frontend||HTML, CSS, JavaScript, Jinja2",
     "Database||SQLite (PostgreSQL ready)"],
    ["AI framework||LangChain + LangGraph",
     "LLM||Groq — GPT-OSS 120B",
     "Knowledge system||Hybrid RAG",
     "User roles||6 (Admin, PM, Engineer, Accountant, Procurement, Viewer)",
     "Main pages||21",
     "Project tabs||12 per project workspace"],
    top=1.5)

# ============================================================
# SLIDE 4 — How It Works
# ============================================================
slide = new_slide("How It Works", "A real-world example: renovating a room")
add_bullets(slide, [
    "Step 1 — Create a Project||Enter project name, location, type, approved budget and room dimensions",
    "Step 2 — Estimate Materials||Calculate tiles, paint, bricks, plaster and other material quantities",
    "Step 3 — Compare Suppliers||Compare quotations, prices, transport charges and delivery times",
    "Step 4 — Manage Construction||Track expenses, labour, inventory, tasks and project progress",
    "Step 5 — Reports & Communication||Generate reports, identify risks, prepare emails and receive alerts",
    "The AI assistant helps the user throughout the entire process",
], font_size=17)

# ============================================================
# SLIDE 5 — Application Pages
# ============================================================
slide = new_slide("Application Modules", "21 main pages across 5 navigation sections")
add_two_col(slide,
    ["Workspace (3 pages)",
     "  Overview Dashboard",
     "  My Projects",
     "  AI Assistant",
     "",
     "Construction (8 pages)",
     "  Cost Estimator",
     "  Bill of Quantities (BOQ)",
     "  Budget & Expenses",
     "  Inventory",
     "  Suppliers & Prices",
     "  Procurement",
     "  Labour",
     "  Project Schedule"],
    ["Intelligence (3 pages)",
     "  Analytics",
     "  Knowledge Base",
     "  Reports",
     "",
     "Communication (4 pages)",
     "  Mail Centre",
     "  Notifications",
     "  Automations",
     "  Approval Centre",
     "",
     "Administration (3 pages)",
     "  Profile",
     "  Settings",
     "  Activity Logs"],
    top=1.5)

# ============================================================
# SLIDE 6 — User Roles
# ============================================================
slide = new_slide("User Roles & Access Control", "Role-Based Access Control (RBAC)")
add_bullets(slide, [
    "Administrator||Full permissions and application administration",
    "Project Manager||Plans projects, manages budgets, tasks, suppliers and approvals",
    "Site Engineer||Manages site activities, inventory, labour and schedules",
    "Accountant||Manages expenses, financial records, BOQ and reports",
    "Procurement Manager||Manages suppliers, quotations and material purchasing",
    "Viewer||Limited read-only access without management permissions",
    "Each role has specific capabilities enforced on the backend",
], font_size=17)

# ============================================================
# SLIDE 7 — System Architecture
# ============================================================
slide = new_slide("System Architecture", "Traditional software + Agentic AI working together")
add_two_col(slide,
    ["Traditional Software",
     "Authentication & sessions",
     "Database operations",
     "Material calculations",
     "Budget management",
     "Supplier records",
     "Scheduling",
     "Report generation"],
    ["Agentic AI System",
     "Natural language understanding",
     "Intelligent task routing",
     "Dynamic tool selection",
     "Multi-step reasoning",
     "Knowledge retrieval (RAG)",
     "AI-generated recommendations",
     "Conversational assistance"],
    top=1.5)

# ============================================================
# SLIDE 8 — Generative AI
# ============================================================
slide = new_slide("How Generative AI Is Used", "LLM: Groq GPT-OSS 120B")
add_bullets(slide, [
    "The LLM understands user requests in natural language",
    "It interprets retrieved information from databases and documents",
    "It selects appropriate tools to perform real operations",
    "It generates explanations, summaries and email drafts",
    "It routes complex requests to specialist agents",
    "The LLM is NOT the database, calculator or email service — it uses tools for those",
    "Example: 'Analyse my project, check budget, find material shortages and prepare a report'",
], font_size=17)

# ============================================================
# SLIDE 9 — Multi-Agent Architecture
# ============================================================
slide = new_slide("Multi-Agent Architecture", "Supervisor + 12 specialist routes + Verifier")
add_bullets(slide, [
    "Supervisor Agent||Understands and routes user requests",
    "Planning Agent||Construction project planning assistance",
    "Estimation Agent||Material quantities and cost calculations",
    "Budget Agent||Expenses and budget utilization analysis",
    "Procurement Agent||Supplier comparison and purchasing info",
    "Inventory Agent||Material stock and shortage checks",
    "Scheduling Agent||Tasks, dependencies and delays",
    "Research Agent||Retrieves info from uploaded documents",
    "Analytics Agent||Trends, anomalies and project health",
    "Reporting Agent||Generates and summarizes reports",
    "Communication Agent||Prepares email drafts",
    "Approvals Agent||Manages approval requests",
    "Verifier||Reviews and consolidates final results",
], font_size=15)

# ============================================================
# SLIDE 10 — Tool Calling
# ============================================================
slide = new_slide("Tool Calling", "AI performs real actions, not just text")
add_bullets(slide, [
    "User: 'How much budget is remaining?'",
    "LLM identifies a financial information request",
    "Budget agent selects the appropriate budget tool",
    "Tool retrieves approved budget and expenses from database",
    "Calculation: \u20b92,00,000 \u2212 \u20b91,25,000 = \u20b975,000",
    "Final response: 'Your remaining budget is \u20b975,000'",
    "Tool categories: Project, Estimation, Budget, Inventory, Procurement, Scheduling, RAG, Analytics, Report, Email, Approval",
], font_size=17)

# ============================================================
# SLIDE 11 — RAG
# ============================================================
slide = new_slide("Retrieval-Augmented Generation (RAG)", "AI answers from your uploaded documents")
add_two_col(slide,
    ["Document Types",
     "PDF / DOCX",
     "Excel / CSV",
     "TXT / MD",
     "",
     "Processing",
     "Text extraction",
     "Document chunking",
     "Duplicate detection"],
    ["Retrieval Methods",
     "BM25 (keyword search)",
     "TF-IDF (vector search)",
     "Reciprocal Rank Fusion (hybrid)",
     "",
     "Output",
     "Answer with source citations",
     "Graceful 'not found' response"],
    top=1.5)

# ============================================================
# SLIDE 12 — Data Sources
# ============================================================
slide = new_slide("Where Does the Data Come From?", "AI does not know prices automatically")
add_bullets(slide, [
    "Project name, location, budget||User input",
    "Room measurements||User input",
    "Actual expenses||Accountant or project manager",
    "Material quantities||Python estimation formulas",
    "Supplier prices||Recorded quotations and imported data",
    "Inventory stock||Site engineer or inventory records",
    "Construction guidelines||Uploaded knowledge documents",
    "Weather information||Open-Meteo API",
    "Demo data||Synthetic demo dataset",
], font_size=17)

# ============================================================
# SLIDE 13 — Technology Stack
# ============================================================
slide = new_slide("Technology Stack", "Complete tech stack")
add_two_col(slide,
    ["Backend & Data",
     "Python 3.12, FastAPI, Uvicorn",
     "SQLAlchemy, SQLite / PostgreSQL",
     "Pydantic, NumPy",
     "APScheduler, SMTP / Gmail",
     "ReportLab, OpenPyXL",
     "PyMuPDF, python-docx"],
    ["AI & Frontend",
     "LangChain, LangGraph",
     "Groq GPT-OSS 120B",
     "BM25, TF-IDF, RRF (RAG)",
     "HTML5, CSS3, JavaScript",
     "Jinja2, Chart.js",
     "SSE, Marked.js, DOMPurify"],
    top=1.5)

# ============================================================
# SLIDE 14 — Conclusion
# ============================================================
slide = new_slide("Conclusion & Future Scope", "Summary")
add_bullets(slide, [
    "BuildBudget AI combines traditional construction management with Agentic AI",
    "21 pages, 6 roles, 12 project workspace tabs",
    "Multi-agent architecture with tool calling and hybrid RAG",
    "Human-in-the-loop approvals for sensitive operations",
    "Automated notifications and scheduled monitoring",
    "Future: Dedicated admin panel, shared project access, Gmail sync, live market prices, advanced ML forecasting",
    "Presented as a construction planning platform, not a replacement for licensed engineers",
], font_size=17)

# Save
out_path = "BuildBudget_AI_Presentation.pptx"
prs.save(out_path)
print(f"Saved: {out_path}  ({len(prs.slides)} slides)")
