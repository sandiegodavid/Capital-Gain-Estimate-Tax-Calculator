"""Shared XlsxWriter formats and small worksheet layout helpers."""

from __future__ import annotations

from collections.abc import Sequence

import xlsxwriter

FormatMap = dict[str, xlsxwriter.format.Format]


def create_formats(workbook: xlsxwriter.Workbook) -> FormatMap:
    """Create the report's reusable visual and numeric formats."""
    body = {"font_name": "Aptos", "font_size": 10, "font_color": "#000000", "valign": "vcenter"}
    return {
        "title": workbook.add_format({"font_name": "Aptos Display", "font_size": 18, "bold": True, "font_color": "#FFFFFF", "bg_color": "#15324B", "valign": "vcenter"}),
        "subtitle": workbook.add_format({"font_name": "Aptos", "font_size": 10, "italic": True, "font_color": "#5B6573"}),
        "section": workbook.add_format({"font_name": "Aptos", "font_size": 11, "bold": True, "font_color": "#FFFFFF", "bg_color": "#15324B", "valign": "vcenter"}),
        "header": workbook.add_format({"font_name": "Aptos", "font_size": 10, "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "align": "center", "valign": "vcenter", "text_wrap": True, "top": 1, "bottom": 1, "top_color": "#9CC2E5", "bottom_color": "#9CC2E5"}),
        "body": workbook.add_format(body),
        "text_wrap": workbook.add_format({**body, "text_wrap": True}),
        "formula": workbook.add_format({**body, "font_color": "#008000", "align": "right"}),
        "currency": workbook.add_format({**body, "align": "right", "num_format": '$#,##0.00;[Red]($#,##0.00);-'}),
        "currency_formula": workbook.add_format({**body, "font_color": "#008000", "align": "right", "num_format": '$#,##0.00;[Red]($#,##0.00);-'}),
        "whole_formula": workbook.add_format({**body, "font_color": "#008000", "align": "right", "num_format": '$#,##0;[Red]($#,##0);-'}),
        "count": workbook.add_format({**body, "align": "right", "num_format": '#,##0;[Red](#,##0);-'}),
        "quantity": workbook.add_format({**body, "align": "right", "num_format": '#,##0.####;[Red](#,##0.####);-'}),
        "percent": workbook.add_format({**body, "align": "right", "num_format": '0.0%;[Red](0.0%);-'}),
        "date": workbook.add_format({**body, "align": "right", "num_format": "yyyy-mm-dd"}),
        "kpi_label": workbook.add_format({"font_name": "Aptos", "font_size": 10, "bold": True, "font_color": "#15324B", "bg_color": "#DCEAF7", "align": "center", "top": 1, "bottom": 1, "top_color": "#9CC2E5", "bottom_color": "#9CC2E5"}),
        "kpi": workbook.add_format({"font_name": "Aptos", "font_size": 16, "bold": True, "font_color": "#008000", "align": "center", "num_format": '$#,##0;[Red]($#,##0);-', "bottom": 1, "bottom_color": "#9CC2E5"}),
        "audit_label": workbook.add_format({"font_name": "Aptos", "font_size": 10, "bold": True, "font_color": "#15324B", "bg_color": "#DCEAF7", "align": "center"}),
        "audit_status": workbook.add_format({"font_name": "Aptos", "font_size": 14, "bold": True, "font_color": "#008000", "align": "center"}),
        "total": workbook.add_format({**body, "bold": True}),
        "total_whole": workbook.add_format({**body, "bold": True, "align": "right", "num_format": '$#,##0;[Red]($#,##0);-'}),
        "note": workbook.add_format({"font_name": "Aptos", "font_size": 10, "bold": True, "font_color": "#7A4B00", "bg_color": "#FFF4CC", "text_wrap": True, "valign": "vcenter"}),
        "legend": workbook.add_format({"font_name": "Aptos", "font_size": 10, "bold": True, "font_color": "#15324B", "bg_color": "#DCEAF7"}),
        "green": workbook.add_format({**body, "font_color": "#008000"}),
    }


def write_title(worksheet, title: str, subtitle: str, column_count: int, formats: FormatMap) -> None:
    """Apply the consistent title area used by every report worksheet."""
    worksheet.merge_range(0, 0, 0, column_count - 1, title, formats["title"])
    worksheet.merge_range(1, 0, 1, column_count - 1, subtitle, formats["subtitle"])
    worksheet.set_row(0, 32)
    worksheet.set_row(1, 22)
    worksheet.hide_gridlines(2)
    worksheet.set_margins(left=0.7, right=0.7)


def write_headers(worksheet, row: int, headers: Sequence[str], formats: FormatMap, start_column: int = 0) -> None:
    """Write one standardized header row."""
    worksheet.set_row(row, 30)
    for column, label in enumerate(headers, start_column):
        worksheet.write(row, column, label, formats["header"])
