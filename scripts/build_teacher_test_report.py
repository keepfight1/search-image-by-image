from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "teacher_test_cases"
DATA_PATH = PACKAGE_DIR / "批量测试结果.json"
OUTPUT_PATH = PACKAGE_DIR / "寻猫平台测试报告.docx"

GREEN = "245C3B"
LIGHT_GREEN = "EAF3EC"
LIGHT_GRAY = "F3F5F4"
MID_GRAY = "D9DFDB"
TEXT = RGBColor(32, 49, 39)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = MID_GRAY, size: str = "6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        item = borders.find(qn(tag))
        if item is None:
            item = OxmlElement(tag)
            borders.append(item)
        item.set(qn("w:val"), "single")
        item.set(qn("w:sz"), size)
        item.set(qn("w:color"), color)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_table_widths(table, widths: list[float]) -> None:
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    total_twips = round(sum(widths) * 1440)
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(total_twips))
    for index, width in enumerate(widths):
        table.columns[index].width = Inches(width)
        grid_col = table._tbl.tblGrid.gridCol_lst[index]
        grid_col.set(qn("w:w"), str(round(width * 1440)))
        for cell in table.columns[index].cells:
            cell.width = Inches(width)


def set_keep_with_next(paragraph) -> None:
    paragraph.paragraph_format.keep_with_next = True


def set_font(run, size: float | None = None, bold: bool | None = None, color=None) -> None:
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def set_cell_text(cell, text: str, *, bold: bool = False, color=None, align=WD_ALIGN_PARAGRAPH.CENTER) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(text)
    set_font(run, 9.2, bold, color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_border(cell)


def add_table(document: Document, headers: list[str], rows: list[list[str]], widths: list[float] | None = None):
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = 1
    if widths:
        set_table_widths(table, widths)
    header = table.rows[0]
    set_repeat_table_header(header)
    for index, text in enumerate(headers):
        set_cell_text(header.cells[index], text, bold=True, color=RGBColor(255, 255, 255))
        set_cell_shading(header.cells[index], GREEN)
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, text in enumerate(values):
            set_cell_text(cells[index], str(text))
            if widths:
                cells[index].width = Inches(widths[index])
            if row_index % 2:
                set_cell_shading(cells[index], LIGHT_GRAY)
    document.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_heading(document: Document, text: str, level: int = 1):
    paragraph = document.add_heading(text, level=level)
    set_keep_with_next(paragraph)
    return paragraph


def add_body(document: Document, text: str, *, bold_prefix: str | None = None):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(5)
    paragraph.paragraph_format.line_spacing = 1.15
    if bold_prefix and text.startswith(bold_prefix):
        first = paragraph.add_run(bold_prefix)
        set_font(first, 10.5, True, TEXT)
        rest = paragraph.add_run(text[len(bold_prefix) :])
        set_font(rest, 10.5, False, TEXT)
    else:
        run = paragraph.add_run(text)
        set_font(run, 10.5, False, TEXT)
    return paragraph


def add_kpis(document: Document, items: list[tuple[str, str]]) -> None:
    table = document.add_table(rows=1, cols=len(items))
    table.alignment = 1
    set_table_widths(table, [1.62] * len(items))
    for index, (value, label) in enumerate(items):
        cell = table.rows[0].cells[index]
        set_cell_shading(cell, LIGHT_GREEN)
        set_cell_border(cell, "C8DACA", "8")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        value_run = p.add_run(value + "\n")
        set_font(value_run, 16, True, RGBColor(36, 92, 59))
        label_run = p.add_run(label)
        set_font(label_run, 8.5, False, TEXT)
    document.add_paragraph().paragraph_format.space_after = Pt(0)


def fit_picture(run, image_path: Path, max_width: float = 1.95, max_height: float = 1.8) -> None:
    with Image.open(image_path) as image:
        width, height = image.size
    scale = min(max_width / width, max_height / height)
    run.add_picture(str(image_path), width=Inches(width * scale), height=Inches(height * scale))


def add_case_page(document: Document, case: dict) -> None:
    add_heading(document, f"典型案例 {case['number']}  {case['title']}", 1)
    add_body(document, case["conclusion"])

    image_table = document.add_table(rows=2, cols=3)
    image_table.autofit = False
    images = [case["query_image"], case["target_image"], case["distractor_image"]]
    captions = ["查询照片", "正确发现线索", "相似干扰猫"]
    for index, (relative, caption) in enumerate(zip(images, captions)):
        image_cell = image_table.rows[0].cells[index]
        image_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = image_cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fit_picture(p.add_run(), PACKAGE_DIR / relative)
        caption_cell = image_table.rows[1].cells[index]
        set_cell_text(caption_cell, caption, bold=True)
        set_cell_shading(caption_cell, LIGHT_GREEN)
    document.add_paragraph().paragraph_format.space_after = Pt(0)

    before = case["before"]
    after = case["after"]
    add_table(
        document,
        ["阶段", "正确线索排名", "候选线索数", "阈值内候选数"],
        [
            ["筛选前", str(before["target_rank"]), str(before["candidate_count"]), str(before["accepted_candidate_count"])],
            ["筛选后", str(after["target_rank"]), str(after["candidate_count"]), str(after["accepted_candidate_count"])],
        ],
        [1.4, 1.7, 1.7, 1.7],
    )

    add_body(document, "演示条件：" + case["filter_text"], bold_prefix="演示条件：")
    rows = []
    for row in case["comparison_rows"]:
        rows.append(
            [
                row["label"],
                str(row["rank"]),
                f"{row['score']:.4f}",
                "橘白" if case["key"] == "same_color" else row["desc"].get("coat_color", ""),
                row["district"],
                row["event_time"],
            ]
        )
    add_table(
        document,
        ["对象", "排名", "相似分", "毛色", "区县", "目击时间"],
        rows,
        [1.6, 0.6, 0.8, 0.7, 0.8, 1.65],
    )
    if case["key"] == "same_color":
        add_body(document, "解读：两只猫均呈橘白色且处于同一区县，正确身份相似分 0.9223，显著高于同色干扰猫 0.3727，说明排序并非只按毛色。")
    elif case["key"] == "location":
        add_body(document, "解读：错误第 1 名在江汉区；限定硚口区后被排除，正确身份从第 2 升到第 1，候选线索由 152 条降到 26 条。")
    else:
        add_body(document, "解读：查询猫在 2026 年走失，2025 年的目击早于走失日期，不可能是本次走失后的线索；时间过滤后正确身份从第 2 升到第 1。")


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("第 ")
    set_font(run, 8.5, False, RGBColor(100, 110, 104))
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run._r.addnext(fld)
    suffix = paragraph.add_run(" 页")
    set_font(suffix, 8.5, False, RGBColor(100, 110, 104))


def configure_document(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)
    add_page_number(section.footer.paragraphs[0])

    normal = document.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = TEXT

    title = document.styles["Title"]
    title.font.name = "Microsoft YaHei"
    title._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    title.font.size = Pt(26)
    title.font.bold = True
    title.font.color.rgb = RGBColor(0, 0, 0)

    for name, size in (("Heading 1", 16), ("Heading 2", 12.5)):
        style = document.styles[name]
        style.font.name = "Microsoft YaHei"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(6)
        style.paragraph_format.space_after = Pt(6)


def main() -> None:
    package = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    document = Document()
    configure_document(document)

    title = document.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("寻猫平台典型用例与批量测试报告")
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("固定测试集 · 图像检索 · 地点与时间联合筛选")
    set_font(run, 11, False, RGBColor(80, 96, 86))
    subtitle.paragraph_format.space_after = Pt(14)

    image_only = package["batch_metrics"]["image_only"]
    location = package["batch_metrics"]["location"]
    add_kpis(
        document,
        [
            (f"{image_only['top1']['rate']:.1%}", "仅图片 Top-1"),
            (f"{location['top1']['rate']:.1%}", "加入地点 Top-1"),
            (str(package["gallery_reports"]), "活跃发现线索"),
            (str(package["gallery_vectors"]), "图库图片向量"),
        ],
    )

    add_heading(document, "测试目的", 1)
    add_body(document, "验证平台能否区分相同毛色的不同猫，并验证区县与走失日期能否排除空间或时间上不合理的相似候选。测试同时给出 80 张同猫查询的批量结果和 20 张库外查询的开放集观察。")

    add_heading(document, "测试数据与方法", 1)
    add_table(
        document,
        ["项目", "设置"],
        [
            ["正样本", "80 张查询图；图库中各有同一只猫的其他照片"],
            ["库外样本", "20 张查询图；图库中没有对应身份"],
            ["区域分布", "武汉市江岸区 27、江汉区 27、硚口区 26"],
            ["时间分布", "2025 年 40 条、2026 年 40 条"],
            ["匹配规则", "猫检测 → 元数据过滤 → 图像向量余弦相似度排序"],
            ["判定阈值", f"相似分不低于 {package['threshold']:.2f} 才列为可联系候选"],
        ],
        [1.35, 5.25],
    )
    add_body(document, "说明：地点与时间由用户填写，系统不会从照片自动推断。相似分用于排序，不等同于身份概率，最终仍需人工核对多张照片和线索详情。")

    for case in package["typical_cases"]:
        document.add_page_break()
        add_case_page(document, case)

    document.add_page_break()
    add_heading(document, "批量测试结果", 1)
    labels = {
        "image_only": "仅图片",
        "location": "图片和地点",
        "time": "图片和走失日期",
        "location_time": "图片 地点和走失日期",
    }
    rows = []
    for key in ("image_only", "location", "time", "location_time"):
        metric = package["batch_metrics"][key]
        rows.append(
            [
                labels[key],
                f"{metric['top1']['count']}/80（{metric['top1']['rate']:.1%}）",
                f"{metric['top5']['count']}/80（{metric['top5']['rate']:.1%}）",
                f"{metric['recall_at_1']['count']}/80（{metric['recall_at_1']['rate']:.1%}）",
                str(metric["median_candidate_count"]),
            ]
        )
    add_table(
        document,
        ["方案", "Top-1", "Top-5", "Recall@1", "候选数中位数"],
        rows,
        [1.4, 1.2, 1.2, 1.3, 1.4],
    )
    add_body(document, "Top-1/Top-5：正确身份是否进入前 1/前 5，不考虑阈值。Recall@1：正确身份排第 1 且相似分达到 0.45。80 张正样本中有 1 张未检测到猫，按失败计入分母。")

    add_heading(document, "结果解读", 2)
    add_table(
        document,
        ["观察", "结论"],
        [
            ["地点筛选", "Top-1 从 87.5% 升到 93.8%，候选数中位数从 152 降到 27"],
            ["时间筛选", "排除走失日期之前的目击，Top-1 为 88.8%，候选数中位数为 112"],
            ["地点和时间", "Top-1 为 93.8%，候选数中位数进一步降到 14"],
            ["库外查询", f"20 张中 {package['unknown_queries']['false_candidates']} 张仍出现阈值内候选；开放集误候选率 {package['unknown_queries']['false_candidate_rate']:.0%}"],
            ["单张耗时", f"中位数 {package['latency_seconds']['median']:.3f} 秒，P95 {package['latency_seconds']['p95']:.3f} 秒"],
        ],
        [1.35, 5.25],
    )

    add_heading(document, "课堂演示步骤", 1)
    steps = [
        "双击一键启动脚本，浏览器打开平台；另开 teacher_test_cases/测试用例展示.html 作为结果总览。",
        "同色案例：上传 01_same_color_query.jpg，不填筛选项；展示正确橘白猫排第 1，并与同色干扰猫比较。",
        "地点案例：先上传 02_location_query.jpg 不筛选，再限定武汉市硚口区；展示正确线索从第 2 升到第 1。",
        "时间案例：先上传 03_time_query.jpg 不筛选，再填写走失日期 2026-01-01；展示 2025 年线索被排除。",
        "最后展示本页批量表，并说明元数据负责排除不可能候选，图像模型负责在剩余候选中排序。",
    ]
    for index, step in enumerate(steps, 1):
        p = document.add_paragraph(style=None)
        p.paragraph_format.left_indent = Inches(0.15)
        p.paragraph_format.first_line_indent = Inches(-0.15)
        p.paragraph_format.space_after = Pt(4)
        number = p.add_run(f"{index}. ")
        set_font(number, 10.5, True, RGBColor(36, 92, 59))
        text = p.add_run(step)
        set_font(text, 10.5, False, TEXT)

    add_heading(document, "结论与边界", 1)
    add_body(document, "本次固定测试表明，模型在多数同猫跨照片查询中能把正确身份排在前列；地点和走失日期能显著缩小候选范围，并能纠正部分仅看图片时的错误首位。由于库外查询仍可能出现相似候选，平台应将结果标注为“疑似匹配”，不能替代人工确认。")

    document.core_properties.title = "寻猫平台典型用例与批量测试报告"
    document.core_properties.subject = "图像检索与地点时间筛选测试"
    document.core_properties.author = "寻猫平台项目组"
    document.save(OUTPUT_PATH)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
