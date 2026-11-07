from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "documentacion" / "Proyecto_Tecnico_Flamia_Tesis_APA_7.docx"
OUTPUT = ROOT / "documentacion" / "Proyecto_Final_Seminario_Flamia.docx"


def set_font(run, size=11, bold=None, italic=None):
    run.font.name = "Arial"
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Arial")
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def move_to_start(p, first):
    p._element.getparent().remove(p._element)
    first.addprevious(p._element)


def cover_paragraph(doc, text="", size=12, bold=False, before=0, after=0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = None
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    set_font(r, size=size, bold=bold)
    return p


def add_page_number(paragraph):
    r = paragraph.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = " PAGE "
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    r._r.extend([begin, instr, separate, end]); set_font(r, size=10)


def shade(cell, color="D9EAF2"):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:fill"), color); tcpr.append(shd)


def simple_table(doc, headers, rows, title):
    n = len(doc.tables) + 1
    p = doc.add_paragraph(); p.add_run(f"Tabla {n}").bold = True
    p.paragraph_format.first_line_indent = None; p.paragraph_format.keep_with_next = True
    p = doc.add_paragraph(); r = p.add_run(title); r.italic = True
    p.paragraph_format.first_line_indent = None; p.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=len(headers)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    trpr = t.rows[0]._tr.get_or_add_trPr()
    header_flag = OxmlElement("w:tblHeader"); header_flag.set(qn("w:val"), "true"); trpr.append(header_flag)
    for i, text in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = text; shade(c, "17324D"); c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for rr in c.paragraphs[0].runs: set_font(rr, size=9, bold=True); rr.font.color.rgb = __import__('docx').shared.RGBColor(255,255,255)
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = text; cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if ri % 2: shade(cells[i], "F3F6F8")
            for p in cells[i].paragraphs:
                p.paragraph_format.first_line_indent = None; p.paragraph_format.line_spacing = 1
                for rr in p.runs: set_font(rr, size=9)
    return t


doc = Document(SOURCE)

# Match the page geometry observed in the reference.
section = doc.sections[0]
section.page_width = Inches(8.5); section.page_height = Inches(11)
section.top_margin = Inches(1); section.bottom_margin = Inches(1)
section.left_margin = Inches(1); section.right_margin = Inches(1)
section.different_first_page_header_footer = True

# Replace the prior cover while keeping all project content that follows it.
body = doc._element.body
first_break_p = None
for p in doc.paragraphs:
    if p._element.xpath('.//w:br[@w:type="page"]'):
        first_break_p = p._element
        break
if first_break_p is not None:
    for el in list(body):
        body.remove(el)
        if el is first_break_p:
            break

first = body[0]
cover = [
    cover_paragraph(doc, "UNIVERSIDAD MARIANO GÁLVEZ DE GUATEMALA", 12, True),
    cover_paragraph(doc, "FACULTAD DE INGENIERÍA EN SISTEMAS DE INFORMACIÓN", 12, True),
    cover_paragraph(doc, "", 12, False, after=42),
    cover_paragraph(doc, "FLAMIA SISTEMA WEB PARA LA PLANIFICACIÓN DE RUTAS ENTREGAS Y COBROS", 14, True, after=36),
    cover_paragraph(doc, "ENTREGA DE PROYECTO FINAL", 12, True, after=34),
    cover_paragraph(doc, "[NOMBRE DEL ESTUDIANTE]", 12, True, after=34),
    cover_paragraph(doc, "GUATEMALA, OCTUBRE DE 2026", 12, True),
]
pb = doc.add_paragraph(); pb.add_run().add_break(__import__('docx').enum.text.WD_BREAK.PAGE)
cover.append(pb)
for p in cover:
    move_to_start(p, first)

# Reference-style inner header with title and page number.
h = section.header.paragraphs[0]; h.clear(); h.alignment = WD_ALIGN_PARAGRAPH.RIGHT
r = h.add_run("Flamia Sistema Web de Planificación de Rutas    "); set_font(r, size=10)
add_page_number(h)
fh = section.first_page_header.paragraphs[0]; fh.clear()

# Normalize numbered headings to the punctuation pattern of the reference.
for p in doc.paragraphs:
    text = p.text.strip()
    if p.style and p.style.name.startswith("Heading"):
        text = re.sub(r"^(\d+)\s+(\d+)\s+", r"\1.\2 ", text)
        text = re.sub(r"^(\d+)\s+", r"\1. ", text)
        if text != p.text:
            p.text = text
            for r in p.runs: set_font(r, bold=True, italic=p.style.name == "Heading 3")

# Match the reference's preliminary narrative.
for p in doc.paragraphs:
    if p.text.strip() == "Control documental":
        p.text = "Introducción"; p.style = doc.styles["Heading 1"]
    elif p.text.strip() == "Resumen ejecutivo":
        p.text = "Descripción del proyecto"; p.style = doc.styles["Heading 2"]
    elif p.text.strip() in ("5 Referencias", "5. Referencias"):
        p.text = "5. Bibliografía"; p.style = doc.styles["Heading 1"]

# Replace the short contents block with a Word-generated index and position it
# before the introduction, following the reference document.
content = next((p for p in doc.paragraphs if p.text.strip() == "Contenido"), None)
if content:
    el = content._element
    to_remove = [el]
    nxt = el.getnext()
    while nxt is not None:
        text = "".join(nxt.itertext()).strip()
        if text.lower().startswith("objetivo general"):
            break
        to_remove.append(nxt)
        nxt = nxt.getnext()
    for item in to_remove:
        item.getparent().remove(item)

intro = next((p for p in doc.paragraphs if p.text.strip() == "Introducción"), None)
if intro:
    idx = doc.add_paragraph("Índice")
    idx.alignment = WD_ALIGN_PARAGRAPH.CENTER
    idx.paragraph_format.first_line_indent = None
    for r in idx.runs: set_font(r, size=14, bold=True)
    toc = doc.add_paragraph()
    toc.paragraph_format.first_line_indent = None
    run = toc.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t"); placeholder.text = "El índice se actualizará al abrir el documento."
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, placeholder, end])
    index_break = doc.add_paragraph(); index_break.add_run().add_break(__import__('docx').enum.text.WD_BREAK.PAGE)
    for p in (idx, toc, index_break):
        p._element.getparent().remove(p._element)
        intro._element.addprevious(p._element)

# Insert the elaboration criterion immediately before the technical chapter.
target = next((p for p in doc.paragraphs if p.text.strip().startswith("1. Instrumentos utilizados")), None)
if target:
    hp = doc.add_paragraph("Criterio de Elaboración", style="Heading 2")
    pp = doc.add_paragraph("La documentación se elaboró a partir del repositorio de Flamia, sus modelos, servicios, vistas, pruebas, archivos de configuración y mecanismos de despliegue. Cada afirmación técnica se limita a funciones observables en el código. Los diagramas simplifican la implementación para comunicar actores, secuencias, estados, entidades y responsabilidades sin atribuir capacidades que el sistema no demuestra.")
    hp._element.getparent().remove(hp._element); target._element.addprevious(hp._element)
    pp._element.getparent().remove(pp._element); target._element.addprevious(pp._element)

# Add the recurring source note after every figure, as in the reference.
for p in list(doc.paragraphs):
    if not p._element.xpath('.//w:drawing'):
        continue
    nxt = p._element.getnext()
    while nxt is not None and nxt.tag != qn("w:p"):
        nxt = nxt.getnext()
    if nxt is not None and "Nota. Elaboración propia." in "".join(nxt.itertext()):
        continue
    note = doc.add_paragraph("Nota. Elaboración propia.")
    note.paragraph_format.first_line_indent = None
    note.paragraph_format.space_after = Pt(8)
    for r in note.runs: set_font(r, size=10, italic=True)
    note._element.getparent().remove(note._element)
    p._element.addnext(note._element)

# Additional annexes present in the reference, rewritten for Flamia.
doc.add_page_break()
doc.add_heading("6.3 Matriz de Trazabilidad Funcional", level=2)
simple_table(doc, ["Necesidad", "Función de Flamia", "Soporte técnico", "Comprobación"], [
    ["Organizar entregas", "Registro y filtrado de pedidos", "Order, OrderItem y API", "Crear un pedido y consultar su estado"],
    ["Optimizar recorridos", "Planificación con Dijkstra o A estrella", "TripPlanner y RouteOptimizer", "Comparar ruta, distancia y costo calculados"],
    ["Controlar la flota", "Vehículos y conductores", "Vehicle, Driver y permisos", "Asignar un recurso activo a un viaje"],
    ["Registrar cobros", "Pagos, abonos y crédito", "Payment con UUID único", "Repetir una solicitud sin duplicar el cobro"],
    ["Dar seguimiento", "Estados y eventos del viaje", "Trip, RouteStop y TripEvent", "Iniciar, completar o cancelar con trazabilidad"],
    ["Apoyar decisiones", "Reportes de venta, distancia y combustible", "Consultas y serialización", "Contrastar el reporte con operaciones registradas"],
], "Matriz de Trazabilidad entre Necesidades, Funciones y Comprobación")

doc.add_heading("6.4 Pruebas de Verificación de una Misma Función", level=2)
doc.add_paragraph("La función seleccionada es la planificación de un viaje. Las pruebas positiva, negativa y de límite verifican que el sistema cree recorridos válidos, rechace entradas incoherentes y controle la capacidad disponible.")
simple_table(doc, ["Tipo", "Datos de prueba", "Resultado esperado"], [
    ["Positiva", "Vehículo activo, conductor activo y pedidos pendientes dentro de la capacidad", "Se crea el viaje con paradas, distancia y costos"],
    ["Negativa", "Pedido entregado o vehículo inactivo", "La operación se rechaza y no modifica datos"],
    ["Límite", "Peso total igual a la capacidad del vehículo", "La planificación se acepta sin exceder la capacidad"],
    ["Idempotencia", "Repetición de un cobro con el mismo UUID", "Se conserva un solo registro financiero"],
], "Pruebas Positiva, Negativa, de Límite e Idempotencia")

doc.add_heading("6.5 Lectura de Evidencias y Control Documental", level=2)
simple_table(doc, ["Evidencia", "Permite concluir", "No permite concluir"], [
    ["Código y modelos", "Estructura, reglas y relaciones implementadas", "Rendimiento real bajo carga"],
    ["Pruebas automatizadas", "Comportamiento de escenarios cubiertos", "Ausencia total de defectos"],
    ["Configuración de despliegue", "Proceso previsto para publicar", "Disponibilidad permanente"],
    ["Diagramas", "Relaciones y flujos simplificados", "Detalle completo de cada línea de código"],
    ["Matriz de riesgos", "Prioridades técnicas estimadas", "Frecuencia estadística observada"],
], "Alcance de las Evidencias Técnicas del Proyecto")
doc.add_heading("Mantenimiento del Documento", level=3)
doc.add_paragraph("Cuando cambie una entidad se actualizarán el diagrama entidad relación, el glosario y las pruebas asociadas. Los cambios en permisos requieren revisar casos de uso y riesgos. Las modificaciones del planificador exigen actualizar el diagrama de secuencia, los criterios de aceptación y las pruebas de rutas. Cada nueva versión debe conservar fecha, responsable y una descripción verificable del cambio.")
simple_table(doc, ["Versión", "Fecha", "Responsable", "Descripción"], [
    ["1.0", "24 de octubre de 2026", "[NOMBRE DEL ESTUDIANTE]", "Documento técnico inicial de Flamia"],
    ["1.1", "24 de octubre de 2026", "[NOMBRE DEL ESTUDIANTE]", "Adaptación al formato del proyecto final y normas APA"],
], "Control Documental de la Entrega")

doc.core_properties.title = "Proyecto final de seminario del sistema Flamia"
doc.core_properties.subject = "Documentación técnica y académica del proyecto Flamia"
doc.save(OUTPUT)
print(OUTPUT)
