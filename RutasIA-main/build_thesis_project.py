from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "documentacion"
FIG = OUT / "figuras_proyecto"
OUT.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)
LOGO = ROOT / "static" / "logistics" / "brand" / "logistiroute-logo.png"
OUTPUT = OUT / "Proyecto_Tecnico_Flamia_Tesis.docx"
DATE = "24 de octubre de 2026"
NAVY, BLUE, PALE, LIGHT, GRAY = "17324D", "276B8E", "EAF3F7", "F4F6F7", "5F6B73"


def font(size=26, bold=False):
    path = r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"
    return ImageFont.truetype(path, size)


def arrow(draw, start, end, color="#276B8E", width=6):
    draw.line((*start, *end), fill=color, width=width)
    x, y = end
    if abs(end[0]-start[0]) >= abs(end[1]-start[1]):
        pts = [(x-18, y-12), (x-18, y+12), (x+2, y)] if x > start[0] else [(x+18,y-12),(x+18,y+12),(x-2,y)]
    else:
        pts = [(x-12,y-18),(x+12,y-18),(x,y+2)] if y > start[1] else [(x-12,y+18),(x+12,y+18),(x,y-2)]
    draw.polygon(pts, fill=color)


def box(draw, xy, title, subtitle="", fill="#EAF3F7", radius=18, title_size=25):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline="#AEBBC3", width=3)
    x1, y1, x2, y2 = xy
    if subtitle:
        # Anchor both blocks from the top so multi-line field lists cannot
        # expand upward and collide with the entity title.
        draw.text(((x1+x2)/2, y1+24), title, font=font(title_size, True), fill="#142033", anchor="ma")
        draw.multiline_text(((x1+x2)/2, y1+68), subtitle, font=font(19), fill="#334552", anchor="ma", align="center", spacing=4)
    else:
        cy = (y1+y2)/2
        draw.multiline_text(((x1+x2)/2, cy), title, font=font(title_size, True), fill="#142033", anchor="mm", align="center", spacing=6)


def create_diagrams():
    # Use cases
    img = Image.new("RGB", (1800, 1100), "white"); d = ImageDraw.Draw(img)
    d.text((900,45), "Diagrama de casos de uso de Flamia", font=font(34,True), fill="#111", anchor="ma")
    actors = [(120,260,"Administrador"),(120,560,"Supervisor"),(120,860,"Operador")]
    for x,y,label in actors:
        d.ellipse((x-22,y-70,x+22,y-26), outline="#17324D", width=5); d.line((x,y-26,x,y+55), fill="#17324D", width=5)
        d.line((x-50,y+3,x+50,y+3), fill="#17324D", width=5); d.line((x,y+55,x-45,y+115), fill="#17324D", width=5); d.line((x,y+55,x+45,y+115), fill="#17324D", width=5)
        d.text((x,y+145),label,font=font(22,True),fill="#17324D",anchor="ma")
    uses=[(620,160,"Gestionar usuarios"),(1100,160,"Gestionar zonas"),(620,340,"Gestionar flota"),(1100,340,"Gestionar catálogos"),(620,520,"Crear entregas"),(1100,520,"Registrar cobros"),(620,700,"Planificar rutas"),(1100,700,"Controlar viajes"),(620,880,"Consultar reportes"),(1100,880,"Visualizar mapa")]
    # admin to all, supervisor to operational, operator to common
    for _,y,_ in uses: d.line((190,260,415,y), fill="#9AA8B1", width=2)
    for x,y,_ in uses[4:]: d.line((190,560,x-205,y), fill="#9AA8B1", width=2)
    for x,y,_ in [uses[4],uses[5],uses[8],uses[9]]: d.line((190,860,x-205,y), fill="#9AA8B1", width=2)
    for x,y,label in uses:
        d.ellipse((x-205,y-58,x+205,y+58),fill="#EAF3F7",outline="#276B8E",width=3); d.text((x,y),label,font=font(23,True),fill="#142033",anchor="mm")
    d.rounded_rectangle((380,90,1510,1010),radius=25,outline="#17324D",width=4); d.text((1430,985),"Sistema Flamia",font=font(20,True),fill="#17324D",anchor="rs")
    img.save(FIG/"01_casos_uso.png")

    # Sequence
    img=Image.new("RGB",(1800,1150),"white"); d=ImageDraw.Draw(img); d.text((900,45),"Diagrama de secuencia para planificar una ruta",font=font(34,True),fill="#111",anchor="ma")
    lifelines=[(180,"Supervisor"),(520,"Interfaz web"),(880,"API Django"),(1240,"TripPlanner"),(1580,"Base de datos")]
    for x,label in lifelines:
        box(d,(x-125,110,x+125,190),label,fill="#EAF3F7",title_size=22); d.line((x,190,x,1080),fill="#8C9AA4",width=3)
    steps=[(250,180,520,"1 Selecciona vehículo y entregas"),(350,520,880,"2 POST api trips plan"),(450,880,1240,"3 Validar rol y datos"),(550,1240,1580,"4 Consultar pedidos y conexiones"),(650,1580,1240,"5 Entidades cargadas"),(750,1240,1240,"6 Calcular ruta y costos"),(850,1240,1580,"7 Crear viaje paradas y evento"),(950,1580,880,"8 Confirmar transacción"),(1040,880,520,"9 Devolver viaje serializado")]
    for y,x1,x2,label in steps:
        if x1==x2:
            d.arc((x1,y-20,x1+120,y+45),270,90,fill="#276B8E",width=5); d.text((x1+65,y-32),label,font=font(18),fill="#142033",anchor="ma")
        else:
            arrow(d,(x1,y),(x2,y)); d.text(((x1+x2)/2,y-16),label,font=font(18),fill="#142033",anchor="ms")
    img.save(FIG/"02_secuencia.png")

    # States
    img=Image.new("RGB",(1800,1050),"white"); d=ImageDraw.Draw(img); d.text((900,45),"Diagramas de estado de pedido y viaje",font=font(34,True),fill="#111",anchor="ma")
    d.text((450,130),"Pedido",font=font(28,True),fill="#17324D",anchor="ma")
    order=[(100,300,"Pendiente"),(380,300,"Asignado"),(660,300,"En tránsito"),(940,300,"Entregado")]
    for x,y,l in order: box(d,(x,y,x+210,y+100),l,fill="#EAF3F7",title_size=22)
    for i in range(3): arrow(d,(order[i][0]+210,350),(order[i+1][0]-5,350))
    box(d,(500,490,710,590),"Cancelado",fill="#FCEDEB",title_size=22); arrow(d,(205,405),(500,535),color="#B24B3D"); arrow(d,(485,405),(570,490),color="#B24B3D")
    d.text((450,675),"Viaje",font=font(28,True),fill="#17324D",anchor="ma")
    trip=[(100,790,"Planificado"),(430,790,"En progreso"),(760,790,"Completado")]
    for x,y,l in trip: box(d,(x,y,x+240,y+105),l,fill="#EEF2F5",title_size=22)
    arrow(d,(340,842),(425,842)); arrow(d,(670,842),(755,842)); box(d,(430,925,670,1025),"Cancelado",fill="#FCEDEB",title_size=22); arrow(d,(300,895),(425,970),color="#B24B3D")
    box(d,(1150,735,1690,990),"Reglas clave","Planificar asigna pedidos\nIniciar pone pedidos en ruta\nCompletar registra entregas\nCancelar libera pendientes",fill="#F4F6F7",title_size=22)
    img.save(FIG/"03_estados.png")

    # ER diagram
    img=Image.new("RGB",(2000,1450),"white"); d=ImageDraw.Draw(img); d.text((1000,40),"Diagrama entidad relación simplificado",font=font(34,True),fill="#111",anchor="ma")
    entities={
      "User":{"xy":(80,160,400,330),"f":"id PK\nusername\npassword"},"UserProfile":{"xy":(520,160,840,330),"f":"id PK\nuser_id FK\nrole"},
      "Department":{"xy":(1040,120,1380,320),"f":"id PK\ncode\nname\nlatitude longitude"},"RouteConnection":{"xy":(1540,120,1920,340),"f":"id PK\norigin_id FK\ndestination_id FK\ndistance_km"},
      "Driver":{"xy":(80,520,400,700),"f":"id PK\nname\nlicense_number\nis_active"},"Vehicle":{"xy":(520,500,870,720),"f":"id PK\nplate\ncapacity_kg\ndriver_id FK\ndepartment_id FK"},
      "Store":{"xy":(1040,500,1380,730),"f":"id PK\nname\ndepartment_id FK\ncoordinates\nproduct_type"},"Product":{"xy":(1580,520,1900,700),"f":"id PK\nname\nunit_price\nunit_weight_kg"},
      "Order":{"xy":(110,920,450,1160),"f":"id PK\ncode\nstore_id FK\norigin_id FK\ndestination_id FK\nstatus"},"OrderItem":{"xy":(570,930,900,1150),"f":"id PK\norder_id FK\nproduct_id FK\nquantity subtotal"},
      "Trip":{"xy":(1050,900,1400,1170),"f":"id PK\ncode\nvehicle_id FK\ndriver_id FK\norigin destination\ndistance costs status"},"RouteStop":{"xy":(1570,900,1920,1160),"f":"id PK\ntrip_id FK\norder_id FK\nstore_id FK\nsequence status"},
      "Payment":{"xy":(500,1250,850,1410),"f":"id PK uuid\nstore order trip FK\namount method"},"TripEvent":{"xy":(1100,1250,1450,1410),"f":"id PK\ntrip_id FK\nnote timestamps"},
    }
    links=[("User","UserProfile","1 a 1"),("Department","RouteConnection","1 a N"),("Driver","Vehicle","1 a N"),("Department","Vehicle","1 a N"),("Department","Store","1 a N"),("Store","Order","1 a N"),("Order","OrderItem","1 a N"),("Product","OrderItem","1 a N"),("Vehicle","Trip","1 a N"),("Trip","RouteStop","1 a N"),("Order","RouteStop","1 a N"),("Store","Payment","1 a N"),("Trip","TripEvent","1 a N")]
    for a,b,label in links:
        A=entities[a]["xy"]; B=entities[b]["xy"]; p1=((A[0]+A[2])//2,(A[1]+A[3])//2); p2=((B[0]+B[2])//2,(B[1]+B[3])//2); d.line((*p1,*p2),fill="#90A0AA",width=3)
        d.text(((p1[0]+p2[0])/2,(p1[1]+p2[1])/2),label,font=font(16,True),fill="#276B8E",anchor="mm",stroke_width=3,stroke_fill="white")
    for name,info in entities.items(): box(d,info["xy"],name,info["f"],fill="#F4F6F7",title_size=21)
    img.save(FIG/"04_entidad_relacion.png")

    # Architecture patterns
    img=Image.new("RGB",(1800,1050),"white"); d=ImageDraw.Draw(img); d.text((900,45),"Patrones y capas de arquitectura",font=font(34,True),fill="#111",anchor="ma")
    layers=[(110,"Presentación","views serializers templates app.js"),(285,"Aplicación","TripPlanner y TripLifecycleService"),(460,"Dominio","Dijkstra A estrella Haversine reglas"),(635,"Infraestructura","ORM PostgreSQL scraping mapas despliegue")]
    for y,t,s in layers: box(d,(220,y,1580,y+120),t,s,fill="#EAF3F7" if y in (110,460) else "#F4F6F7",title_size=26)
    for y in (230,405,580): arrow(d,(900,y),(900,y+50))
    box(d,(220,820,1580,990),"Patrones aplicados","MTV  |  Capa de servicios  |  ORM  |  Configuración externa  |  Transacciones atómicas",fill="#EAF3F7",title_size=25)
    img.save(FIG/"05_patrones.png")

    # Mind map
    img=Image.new("RGB",(1900,1200),"white"); d=ImageDraw.Draw(img); d.ellipse((750,450,1150,750),fill="#17324D"); d.text((950,600),"FLAMIA",font=font(44,True),fill="white",anchor="mm")
    nodes=[(210,130,"Tecnología","Python Django\nPostgreSQL JavaScript"),(800,70,"Operación","Entregas rutas\ncobros reportes"),(1390,150,"Optimización","Dijkstra A estrella\nHaversine"),(1450,800,"Calidad","Pruebas seguridad\nrespaldos monitoreo"),(800,950,"Usuarios","Administrador\nSupervisor Operador"),(180,800,"Datos","Tiendas productos\nvehículos pedidos")]
    center=(950,600)
    for x,y,_,_ in nodes: d.line((*center,x+150,y+85),fill="#276B8E",width=7)
    for x,y,t,s in nodes: box(d,(x,y,x+300,y+170),t,s,fill="#EAF3F7",title_size=25)
    d.ellipse((750,450,1150,750),fill="#17324D"); d.text((950,600),"FLAMIA",font=font(44,True),fill="white",anchor="mm")
    img.save(FIG/"06_mapa_mental.png")


def shade(cell, fill):
    pr=cell._tc.get_or_add_tcPr(); node=pr.find(qn("w:shd"))
    if node is None: node=OxmlElement("w:shd"); pr.append(node)
    node.set(qn("w:fill"),fill)


def margins(cell, v=110, h=120):
    pr=cell._tc.get_or_add_tcPr(); mar=pr.first_child_found_in("w:tcMar")
    if mar is None: mar=OxmlElement("w:tcMar"); pr.append(mar)
    for name,val in (("top",v),("bottom",v),("start",h),("end",h)):
        n=OxmlElement(f"w:{name}"); n.set(qn("w:w"),str(val)); n.set(qn("w:type"),"dxa"); mar.append(n)


def repeat_header(row):
    pr=row._tr.get_or_add_trPr(); n=OxmlElement("w:tblHeader"); n.set(qn("w:val"),"true"); pr.append(n)


def table(doc, headers, rows, widths=None):
    t=doc.add_table(rows=1,cols=len(headers)); t.style="Table Grid"; t.alignment=WD_TABLE_ALIGNMENT.CENTER
    repeat_header(t.rows[0])
    for i,h in enumerate(headers):
        c=t.rows[0].cells[i]; c.text=str(h); shade(c,NAVY); margins(c); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for r in c.paragraphs[0].runs: r.font.bold=True; r.font.color.rgb=RGBColor(255,255,255); r.font.size=Pt(9)
    for ri,row in enumerate(rows):
        cells=t.add_row().cells
        for i,val in enumerate(row):
            cells[i].text=str(val); margins(cells[i]); cells[i].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if ri%2: shade(cells[i],LIGHT)
            for p in cells[i].paragraphs:
                for r in p.runs: r.font.size=Pt(8.6)
    if widths:
        for row in t.rows:
            for i,w in enumerate(widths): row.cells[i].width=Inches(w)
    doc.add_paragraph().paragraph_format.space_after=Pt(2)
    return t


def setup(doc):
    sec=doc.sections[0]; sec.top_margin=Inches(.72); sec.bottom_margin=Inches(.72); sec.left_margin=Inches(.82); sec.right_margin=Inches(.82)
    normal=doc.styles["Normal"]; normal.font.name="Aptos"; normal.font.size=Pt(10.5); normal.font.color.rgb=RGBColor.from_string("20282D"); normal.paragraph_format.space_after=Pt(6); normal.paragraph_format.line_spacing=1.13
    for name,size,before,after in (("Title",28,0,12),("Heading 1",19,16,7),("Heading 2",14,12,5),("Heading 3",11.5,9,3)):
        st=doc.styles[name]; st.font.name="Aptos Display"; st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor(0,0,0); st.paragraph_format.space_before=Pt(before); st.paragraph_format.space_after=Pt(after); st.paragraph_format.keep_with_next=True
    h=sec.header.paragraphs[0]; h.text="Proyecto técnico Flamia"; h.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    for r in h.runs: r.font.size=Pt(8); r.font.color.rgb=RGBColor.from_string(GRAY)
    f=sec.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER; f.add_run("Flamia  |  ").font.size=Pt(8); fld=OxmlElement("w:fldSimple"); fld.set(qn("w:instr"),"PAGE"); f._p.append(fld)
    doc.core_properties.title="Proyecto técnico del sistema Flamia"; doc.core_properties.subject="Documento técnico para proyecto de tesis"; doc.core_properties.author="Proyecto Flamia"


def heading(doc,text,level=1): return doc.add_heading(text,level=level)
def para(doc,text,lead=None):
    p=doc.add_paragraph()
    if lead and text.startswith(lead): p.add_run(lead).bold=True; p.add_run(text[len(lead):])
    else: p.add_run(text)
    return p
def bullets(doc,items,numbered=False):
    for item in items:
        p=doc.add_paragraph(style="List Number" if numbered else "List Bullet"); p.add_run(item)
def figure(doc,path,caption,width=6.65,alt=None):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.keep_with_next=True
    inline=p.add_run().add_picture(str(path),width=Inches(width)); inline._inline.docPr.set("descr",alt or caption)
    c=doc.add_paragraph(caption); c.alignment=WD_ALIGN_PARAGRAPH.CENTER; c.paragraph_format.space_after=Pt(10)
    for r in c.runs: r.font.size=Pt(8.5); r.font.italic=True; r.font.color.rgb=RGBColor.from_string(GRAY)


def page(doc): doc.add_page_break()


def build():
    create_diagrams(); doc=Document(); setup(doc)
    if LOGO.exists():
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.LEFT; p.add_run().add_picture(str(LOGO),width=Inches(1.65))
    doc.add_paragraph("Proyecto técnico del sistema Flamia",style="Title")
    p=doc.add_paragraph("Sistema web para la planificación de rutas entregas y cobros"); p.style=doc.styles["Subtitle"]
    for lead,text in (("Tipo de documento","Desarrollo técnico para proyecto de tesis"),("Sistema","Flamia"),("Versión","1.0"),("Fecha",DATE)):
        p=doc.add_paragraph(); p.add_run(lead+": ").bold=True; p.add_run(text)
    p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(28); p.add_run("Campos institucionales para completar").bold=True
    table(doc,["Campo","Información"],[["Universidad",""],["Facultad o carrera",""],["Autor",""],["Asesor",""],["Lugar y fecha","Guatemala, 2026"]],[2.0,4.5]); page(doc)

    heading(doc,"Control documental")
    table(doc,["Elemento","Descripción"],[["Objetivo","Documentar la solución tecnológica, su arquitectura, funciones, riesgos y modelos de análisis."],["Alcance","Repositorio RutasIA main y aplicación logística Flamia."],["Audiencia","Comité académico, asesor, desarrolladores y personal de soporte."],["Método","Revisión del código fuente, configuraciones, modelos, API, interfaz y pruebas existentes."],["Estado","Documento preparado para integración en memoria de tesis."]],[1.6,5.0])
    heading(doc,"Resumen ejecutivo",2)
    para(doc,"Flamia es una aplicación web de logística orientada a negocios de distribución de agua purificada y gas. Integra catálogos, clientes, pedidos, cobros, planificación de viajes, visualización cartográfica y reportes. La solución utiliza Django, Python, JavaScript y una base de datos relacional; aplica algoritmos de rutas de costo mínimo y conserva una organización por capas inspirada en Domain Driven Design.")
    para(doc,"El análisis concluye que el sistema cubre el flujo operativo esencial y posee una base técnica adecuada para crecimiento. Las prioridades de fortalecimiento son centralizar los permisos, ampliar pruebas automatizadas, asegurar las migraciones de producción, robustecer la observabilidad y formalizar los respaldos.")
    page(doc)

    heading(doc,"Contenido")
    entries=["1 Instrumentos utilizados","2 Conclusiones","3 Recomendaciones","4 Glosario","5 Bibliografía","6 Anexos"]
    for e in entries: doc.add_paragraph(e,style="List Number")
    heading(doc,"Objetivo general",2); para(doc,"Analizar y documentar los componentes tecnológicos, funcionales y arquitectónicos de Flamia para demostrar la trazabilidad entre el problema logístico, la solución implementada y sus condiciones de operación segura.")
    heading(doc,"Objetivos específicos",2); bullets(doc,["Identificar los instrumentos de desarrollo y despliegue utilizados.","Describir la arquitectura, las funciones y las características del sistema.","Evaluar aspectos técnicos y riesgos operativos o de seguridad.","Representar el comportamiento mediante modelos UML y un diagrama entidad relación.","Establecer conclusiones y recomendaciones aplicables a la evolución del proyecto."])
    page(doc)

    heading(doc,"1 Instrumentos utilizados")
    para(doc,"Los instrumentos corresponden a los lenguajes, marcos de trabajo, motores de datos, servicios, algoritmos y mecanismos de despliegue incorporados en el repositorio. Su selección favorece un desarrollo web de bajo acoplamiento relativo, persistencia transaccional y operación en navegadores de escritorio o dispositivos móviles.")
    heading(doc,"1 1 Lenguaje de programación",2)
    para(doc,"Python es el lenguaje principal del servidor. Gestiona modelos, migraciones, reglas de planificación, serialización, autenticación, comandos administrativos y acceso a fuentes externas. El proyecto declara Python 3.12.8 para producción y Django 6.0.4 como framework web.")
    para(doc,"JavaScript implementa la interacción del cliente. Controla pestañas, formularios, llamadas HTTP, filtros, gráficas, mapas, simulación GPS y sincronización de operaciones pendientes. HTML define la estructura de la interfaz y CSS establece la presentación visual y la adaptación responsiva.")
    table(doc,["Tecnología","Uso en el proyecto","Justificación"],[["Python","Lógica del servidor y algoritmos","Legibilidad, ecosistema Django y soporte para cálculo y automatización."],["JavaScript","Interfaz dinámica y consumo de API","Ejecución nativa en el navegador y actualización sin recargar la página."],["HTML","Estructura semántica","Formularios, navegación y contenido accesible."],["CSS","Diseño responsivo","Presentación consistente en escritorio y móvil."],["SQL mediante ORM","Persistencia","Relaciones, restricciones y consultas sin acoplar la lógica a SQL manual."]],[1.4,2.4,2.8])

    heading(doc,"1 2 Base de datos",2)
    para(doc,"El sistema utiliza SQLite cuando no existe DATABASE_URL, condición apropiada para desarrollo local y demostraciones. En producción utiliza PostgreSQL por medio de psycopg. El ORM de Django abstrae la mayor parte de las operaciones y las migraciones versionan el esquema.")
    bullets(doc,["Integridad referencial mediante claves foráneas y políticas de eliminación.","Restricciones únicas para códigos, placas, licencias, UUID de pagos y relaciones intermedias.","Campos Decimal para importes, distancias, pesos y consumos.","JSONField para almacenar los nodos de una ruta calculada.","Transacciones atómicas en planificación y ciclo de vida de viajes."])

    heading(doc,"1 3 Arquitectura",2)
    para(doc,"La aplicación adopta una arquitectura monolítica modular. El proyecto Django flamia concentra configuración y enrutamiento; la aplicación logistics distribuye responsabilidades en presentación, aplicación, dominio e infraestructura. El cliente se entrega como una interfaz de página única apoyada en endpoints JSON.")
    figure(doc,FIG/"05_patrones.png","Figura 1. Capas y patrones arquitectónicos identificados en Flamia.")
    table(doc,["Capa","Componentes","Responsabilidad"],[["Presentación","views.py, serializers.py, templates y app.js","Recibir solicitudes, aplicar permisos, transformar datos y mostrar la interfaz."],["Aplicación","application/services.py","Coordinar casos de uso y transacciones."],["Dominio","domain/services.py y exceptions.py","Algoritmos de ruta, cálculos y errores de negocio."],["Infraestructura","models.py, fuel_scraper.py, PostgreSQL y servicios cartográficos","Persistencia e integración externa."],["Despliegue","Gunicorn, WhiteNoise y Render","Ejecución WSGI, archivos estáticos y operación en la nube."]],[1.3,2.5,3.0])

    heading(doc,"1 4 Funciones",2)
    table(doc,["Módulo","Funciones principales","Resultado"],[["Autenticación","Inicio y cierre de sesión; identificación de rol.","Acceso controlado."],["Usuarios","Crear cuentas y asignar rol.","Administración de acceso."],["Zonas","Registrar departamentos y coordenadas.","Nodos del grafo logístico."],["Flota","Registrar vehículos, capacidad, rendimiento y conductor.","Recursos disponibles para viajes."],["Tiendas","Mantener clientes, dirección y geolocalización.","Puntos de entrega y cobranza."],["Productos","Definir presentación, precio y peso.","Cálculo de ventas y carga."],["Entregas","Crear y filtrar pedidos con prioridad y estado.","Demanda pendiente de despacho."],["Cobros","Registrar pagos, abonos o crédito.","Historial y saldo por tienda."],["Planificador","Ordenar paradas y calcular rutas y costos.","Viaje planificado."],["Rutas","Iniciar, completar, cancelar y registrar eventos.","Trazabilidad operativa."],["Mapa","Visualizar red, tiendas, recorridos y simulación.","Apoyo geográfico."],["Reportes","Resumir ventas, pagos, saldos, distancia y combustible.","Información para decisión."]],[1.25,3.3,2.3])

    heading(doc,"1 5 Características",2)
    bullets(doc,["Interfaz centralizada con trece módulos funcionales.","Roles de administrador, supervisor y operador.","Planificación con Dijkstra o A estrella sobre una red de zonas.","Cálculo de distancia, consumo en galones, costo de combustible y costo operativo.","Paradas ordenadas con estados Pendiente, Entregado y No entregado.","Registro de cobros idempotente mediante UUID.","Cola local para operaciones compatibles cuando se pierde la conexión.","Mapa interactivo con MapLibre y geometría vial opcional.","Actualización programada del precio de combustible.","Despliegue declarativo mediante render.yaml."])

    heading(doc,"1 6 Análisis técnico",2)
    heading(doc,"Flujo de datos",3)
    para(doc,"El navegador consume endpoints bajo /api. Las vistas autentican la sesión, validan el método y aplican permisos específicos. Los serializadores convierten modelos a JSON. Los servicios de aplicación coordinan transacciones y el ORM persiste los resultados. La respuesta actualiza el estado local y vuelve a renderizar la sección activa.")
    heading(doc,"Optimización de rutas",3)
    para(doc,"RouteOptimizer aplica Dijkstra con una cola de prioridad y distancias acumuladas. AStarOptimizer incorpora la distancia Haversine como heurística cuando existen coordenadas. Para varias paradas, TripPlanner escoge iterativamente la siguiente entrega con menor distancia desde la posición actual. Esta estrategia es eficiente y comprensible, aunque no garantiza el recorrido global óptimo de un problema de ruteo de vehículos.")
    table(doc,["Criterio","Evaluación","Observación"],[["Mantenibilidad","Media alta","Separación por capas y servicios; app.js y una vista principal concentran mucho código."],["Escalabilidad","Media","PostgreSQL y Gunicorn son adecuados; el monolito requerirá caché compartida y colas para crecer."],["Rendimiento","Adecuado para alcance actual","Grafo en caché por 120 segundos y consultas relacionadas optimizadas en endpoints principales."],["Seguridad","Base adecuada con brechas","Sesiones, CSRF y cookies seguras; permisos de escritura no están centralizados."],["Disponibilidad","Dependiente de servicios externos","Mapa, geometría vial y combustible pueden degradarse sin conexión."],["Calidad","Inicial","Existen pruebas básicas; falta cobertura amplia de permisos, estados y finanzas."],["Despliegue","Reproducible parcialmente","Blueprint de Render disponible; migraciones requieren procedimiento explícito."]],[1.35,1.55,3.9])

    heading(doc,"1 7 Análisis de riesgo",2)
    para(doc,"La matriz utiliza probabilidad e impacto cualitativos. La prioridad combina la posibilidad de ocurrencia con el daño operativo, financiero o de seguridad. OWASP Top 10 se adopta como referencia de concientización para riesgos web.")
    table(doc,["ID","Riesgo","Probabilidad","Impacto","Nivel","Tratamiento"],[["R1","Control de acceso inconsistente en endpoints de escritura.","Media","Alto","Alto","Matriz de permisos centralizada y pruebas por rol."],["R2","SECRET_KEY insegura o DEBUG activo en producción.","Baja","Crítico","Alto","Fallar al iniciar si faltan variables seguras."],["R3","Migraciones no aplicadas durante despliegue.","Media","Alto","Alto","Paso de release, respaldo y reversión."],["R4","Pérdida o corrupción de datos.","Baja","Crítico","Alto","Respaldos automáticos y pruebas de restauración."],["R5","Cobro duplicado por reconexión.","Baja","Alto","Medio","Mantener UUID idempotente y auditar sincronización."],["R6","Proveedor cartográfico no disponible.","Media","Medio","Medio","Trazado alternativo y monitoreo de cuota."],["R7","Ruta subóptima con muchas paradas.","Media","Medio","Medio","Evaluar VRP u optimización global."],["R8","Coordenadas incorrectas de tiendas.","Media","Medio","Medio","Validación geográfica y vista previa."],["R9","Falta de registros y alertas.","Media","Alto","Alto","Logging estructurado, métricas y alertas."],["R10","Dependencias vulnerables u obsoletas.","Media","Alto","Alto","Escaneo periódico y política de actualización."],["R11","Cobertura de pruebas insuficiente.","Alta","Medio","Alto","Pruebas de estados, cálculos, permisos y navegador."],["R12","Colisión excepcional de códigos aleatorios.","Baja","Bajo","Bajo","Reintento seguro ante restricción única."]],[.45,2.45,.8,.7,.55,2.1])
    heading(doc,"Controles existentes",3); bullets(doc,["Autenticación de Django y validadores de contraseña.","Protección CSRF y cookies Secure fuera de DEBUG.","Restricciones relacionales y transacciones atómicas.","UUID único para cobros sincronizados.","Separación de variables de entorno y soporte HTTPS detrás de proxy.","Estados explícitos y reglas para el ciclo de vida de viajes."])

    page(doc); heading(doc,"1 8 Diagramas de caso de uso",2)
    para(doc,"Los actores representan niveles de responsabilidad. El administrador mantiene datos maestros y usuarios; el supervisor controla la planificación y el viaje; el operador participa en la operación cotidiana según los permisos autorizados.")
    figure(doc,FIG/"01_casos_uso.png","Figura 2. Casos de uso y actores principales de Flamia.",6.7)
    table(doc,["Actor","Responsabilidad principal"],[["Administrador","Configurar usuarios, zonas, combustible y todos los módulos."],["Supervisor","Planificar y controlar rutas; supervisar pedidos, cobros y reportes."],["Operador","Registrar y consultar la operación habilitada, incluidos pedidos y cobros."]],[1.5,5.1])

    page(doc); heading(doc,"1 9 Diagramas de secuencia",2)
    para(doc,"La secuencia de planificación evidencia la colaboración entre interfaz, vista HTTP, servicio de aplicación y base de datos. La transacción impide que un fallo parcial deje el viaje creado sin pedidos o paradas asociadas.")
    figure(doc,FIG/"02_secuencia.png","Figura 3. Secuencia del caso de uso Planificar ruta.",6.7)

    page(doc); heading(doc,"1 10 Diagramas de estado",2)
    para(doc,"Los estados limitan las acciones válidas y mantienen coherencia entre pedido, viaje y parada. Una cancelación devuelve a Pendiente los pedidos no entregados; una entrega confirmada no debe reabrirse automáticamente.")
    figure(doc,FIG/"03_estados.png","Figura 4. Estados principales de pedidos y viajes.",6.7)

    page(doc); heading(doc,"1 11 Diagrama entidad relación",2)
    para(doc,"El modelo combina catálogos, transacciones y trazabilidad. Order y Trip se relacionan mediante TripOrder; RouteStop conserva la secuencia y el resultado de cada visita. Payment puede asociarse con tienda, pedido y viaje, mientras TripEvent registra la bitácora.")
    figure(doc,FIG/"04_entidad_relacion.png","Figura 5. Entidades, claves y relaciones principales del sistema.",6.7)

    page(doc); heading(doc,"1 12 Patrones de arquitectura",2)
    table(doc,["Patrón","Aplicación en Flamia","Beneficio"],[["Model Template View","Modelos Django, plantillas HTML y vistas HTTP.","Separación estándar del framework."],["Arquitectura por capas","Presentación, aplicación, dominio e infraestructura.","Organización y mantenibilidad."],["Service Layer","TripPlanner y TripLifecycleService.","Casos de uso reutilizables y transaccionales."],["Active Record ORM","Modelos Django encapsulan persistencia y propiedades.","Reduce SQL repetitivo."],["Data Transfer Object implícito","Serializadores producen diccionarios JSON.","Contrato estable con el cliente."],["State Machine implícita","Campos status y servicios controlan transiciones.","Consistencia del ciclo operativo."],["Singleton lógico","FuelPrice.current usa el registro con pk 1.","Una fuente vigente de precios."],["Cache Aside","El grafo se carga bajo demanda y se conserva 120 segundos.","Menos consultas repetidas."],["Offline queue","localStorage retiene solicitudes compatibles.","Resiliencia ante cortes de red."],["Dependency by configuration","Servicios y secretos llegan por variables de entorno.","Portabilidad entre local y producción."]],[1.6,3.0,2.1])
    figure(doc,FIG/"05_patrones.png","Figura 6. Vista consolidada de capas y patrones de arquitectura.",6.7)

    page(doc); heading(doc,"2 Conclusiones")
    conclusions=["Flamia integra en una única solución el ciclo de clientes, productos, pedidos, planificación, entrega, cobro y análisis operativo.","La combinación Python, Django, JavaScript y PostgreSQL es coherente con una aplicación transaccional de logística y ofrece una ruta clara de mantenimiento.","La separación en presentación, aplicación, dominio e infraestructura mejora la comprensión del código, aunque el acoplamiento al ORM confirma que se trata de un DDD pragmático.","Dijkstra y A estrella resuelven adecuadamente caminos en la red de zonas. La selección voraz de múltiples paradas es funcional para el alcance actual, pero no sustituye un optimizador global de flota.","El modelo de datos representa de manera consistente vehículos, conductores, tiendas, productos, pedidos, paradas, pagos y eventos, y utiliza restricciones para proteger relaciones críticas.","Las transacciones atómicas y los estados explícitos reducen inconsistencias durante la creación e inicio de viajes.","La estrategia offline para cobros y el UUID idempotente aportan continuidad operativa, siempre que se supervise la sincronización.","Los riesgos prioritarios se concentran en autorización, configuración productiva, migraciones, pruebas y observabilidad, no en la ausencia de funcionalidad básica.","El sistema constituye una base viable para un proyecto de tesis porque combina ingeniería web, modelado de datos, optimización de rutas, geolocalización y análisis de riesgos."]
    for i,c in enumerate(conclusions,1): para(doc,f"{i}. {c}")

    heading(doc,"3 Recomendaciones")
    table(doc,["Prioridad","Recomendación","Resultado esperado"],[["Inmediata","Definir una matriz de permisos y aplicarla a todos los endpoints POST.","Menor riesgo de acciones no autorizadas."],["Inmediata","Exigir SECRET_KEY, DEBUG False, hosts y orígenes CSRF explícitos en producción.","Configuración segura y verificable."],["Inmediata","Incorporar migraciones, respaldo y plan de reversión al despliegue.","Publicaciones repetibles sin pérdida de datos."],["Alta","Ampliar pruebas de roles, estados, pagos, reportes y sincronización offline.","Detección temprana de regresiones."],["Alta","Implementar logging estructurado, monitoreo y alertas.","Diagnóstico rápido de fallos."],["Alta","Validar importes positivos, coordenadas, cantidades y rangos operativos.","Datos confiables y menor corrección manual."],["Media","Dividir app.js y la vista principal por módulos funcionales.","Mayor mantenibilidad del cliente."],["Media","Evaluar Celery o tareas equivalentes para scraping y procesos lentos.","Menor bloqueo de solicitudes web."],["Media","Comparar la heurística actual con VRP para recorridos de muchas paradas.","Rutas potencialmente más eficientes."],["Continua","Actualizar dependencias y revisar OWASP Top 10.","Reducción del riesgo tecnológico acumulado."]],[1.0,3.5,2.2])

    heading(doc,"4 Glosario")
    terms=[["API","Interfaz que permite al navegador consultar o modificar datos del servidor."],["A estrella","Algoritmo que combina costo acumulado y una heurística para buscar un camino."],["CSRF","Ataque que intenta ejecutar una solicitud usando la sesión de otra persona."],["DDD","Enfoque que organiza el software alrededor del dominio y sus reglas."],["Dijkstra","Algoritmo de camino mínimo para grafos con pesos no negativos."],["Endpoint","Dirección específica de la API que atiende una operación."],["Grafo","Conjunto de nodos y conexiones utilizado para representar la red de rutas."],["Haversine","Fórmula para estimar distancia sobre la superficie terrestre."],["Idempotencia","Propiedad por la cual repetir una solicitud no genera resultados duplicados."],["Migración","Cambio versionado en el esquema de la base de datos."],["MTV","Patrón Model Template View utilizado por Django."],["ORM","Capa que relaciona objetos del lenguaje con tablas de base de datos."],["PWA","Aplicación web con características de instalación y operación parcial sin conexión."],["Ruta","Viaje planificado con vehículo, conductor, pedidos y paradas."],["Service worker","Proceso del navegador que administra caché y funciones fuera de la página."],["Transacción","Conjunto de operaciones que se confirma completo o se revierte."],["UUID","Identificador universal utilizado para distinguir un cobro sincronizado."],["WSGI","Estándar de comunicación entre servidor web y aplicación Python."]]
    table(doc,["Término","Definición"],terms,[1.5,5.2])

    heading(doc,"5 Bibliografía")
    refs=[
      "Django Software Foundation. (2026). Django 6.0 documentation. https://docs.djangoproject.com/en/6.0/",
      "Python Software Foundation. (2026). Python 3 documentation. https://docs.python.org/3/",
      "PostgreSQL Global Development Group. (2026). PostgreSQL documentation. https://www.postgresql.org/docs/",
      "OWASP Foundation. (2026). OWASP Top 10. https://owasp.org/projects/top-ten",
      "MapLibre. (2026). MapLibre GL JS documentation. https://maplibre.org/maplibre-gl-js/docs",
      "HeiGIT. (2026). openrouteservice backend documentation. https://giscience.github.io/openrouteservice/",
      "Render. (2026). Deploy a Django app on Render. https://render.com/docs/deploy-django",
      "WhiteNoise. (2026). WhiteNoise documentation. https://whitenoise.readthedocs.io/en/stable/",
      "Evans, E. (2003). Domain Driven Design Tackling Complexity in the Heart of Software. Addison Wesley.",
      "Fowler, M. (2002). Patterns of Enterprise Application Architecture. Addison Wesley.",
      "Gamma, E., Helm, R., Johnson, R., y Vlissides, J. (1994). Design Patterns. Addison Wesley.",
      "Documentación interna del repositorio RutasIA main: README, modelos, servicios, vistas, serializadores, pruebas y archivos de despliegue. Consulta: 24 de octubre de 2026.",
    ]
    for r in refs:
        p=doc.add_paragraph(r); p.paragraph_format.left_indent=Inches(.3); p.paragraph_format.first_line_indent=Inches(-.3); p.paragraph_format.space_after=Pt(7)

    page(doc); heading(doc,"6 Anexos")
    heading(doc,"6 1 Mapa mental",2)
    para(doc,"El mapa mental sintetiza las dimensiones tecnológica, operativa, algorítmica, humana, de datos y de calidad que componen el proyecto.")
    figure(doc,FIG/"06_mapa_mental.png","Figura 7. Mapa mental del proyecto Flamia.",6.7)
    page(doc); heading(doc,"6 2 Tabla de figuras",2)
    figures=[["Figura 1","Capas y patrones arquitectónicos identificados en Flamia.","Sección 1.3"],["Figura 2","Casos de uso y actores principales de Flamia.","Sección 1.8"],["Figura 3","Secuencia del caso de uso Planificar ruta.","Sección 1.9"],["Figura 4","Estados principales de pedidos y viajes.","Sección 1.10"],["Figura 5","Entidades, claves y relaciones principales del sistema.","Sección 1.11"],["Figura 6","Vista consolidada de capas y patrones de arquitectura.","Sección 1.12"],["Figura 7","Mapa mental del proyecto Flamia.","Anexo 6.1"]]
    table(doc,["Número","Título","Ubicación"],figures,[1.0,4.5,1.2])
    heading(doc,"Correspondencia con el repositorio",2)
    table(doc,["Tema","Archivos principales"],[["Configuración","flamia/settings.py, flamia/urls.py"],["Datos","logistics/models.py, logistics/migrations"],["API","logistics/presentation/views.py y serializers.py"],["Casos de uso","logistics/application/services.py"],["Algoritmos","logistics/domain/services.py"],["Integración externa","logistics/infrastructure/fuel_scraper.py"],["Interfaz","templates/logistics/index.html, static/logistics/app.js y style.css"],["Pruebas","logistics/tests.py"],["Despliegue","render.yaml, Procfile, runtime.txt, requirements.txt"]],[2.1,4.6])
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__": build()
