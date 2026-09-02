"""Excel-compatible report writer backed by XlsxWriter."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, time
from pathlib import Path

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from .excel_charts import add_account_gain_chart, add_monthly_gain_chart
from .excel_styles import create_formats, write_headers, write_title
from .models import NormalizedReport


def _number(value):
    return int(value) if value == value.to_integral_value() else float(value)


def build_workbook(report: NormalizedReport, output_path: Path) -> None:
    """Write the five-sheet report using packages Excel opens natively."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output_path.stem}-", suffix=".xlsx", dir=output_path.parent, delete=False) as handle:
        temporary_path = Path(handle.name)
    try:
        book = xlsxwriter.Workbook(temporary_path)
        book.set_properties({
            "title": f"{report.report_year} Realized Investment Gain/Loss Report",
            "subject": "Audited annual brokerage realized gain/loss consolidation",
            "author": "Capital Gain Estimate Tax Calculator",
        })
        book.set_calc_mode("auto")
        formats = create_formats(book)
        for sheet_name in ("Summary", "Security Summary", "Realized Lots", "Checks", "Source Notes"):
            book.add_worksheet(sheet_name)
        lots_first, lots_last = _write_lots(book, report, formats)
        security_first, security_last = _write_security(book, report, formats, lots_first, lots_last)
        status_row = _write_checks(book, report, formats, lots_first, lots_last, security_first, security_last)
        _write_summary(book, report, formats, lots_first, lots_last, status_row)
        _write_source_notes(book, report, formats)
        book.close()
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_lots(book, report, fmts):
    sheet = book.get_worksheet_by_name("Realized Lots")
    write_title(sheet, f"{report.report_year} Realized Investment Gain/Loss — Tax Lots", f"USD amounts; {len(report.lots)} reported lots sold {min(l.sale_date for l in report.lots):%Y-%m-%d} through {max(l.sale_date for l in report.lots):%Y-%m-%d}.", 18, fmts)
    headers = ["Source", "Account", "Symbol", "Security Description", "Security Type", "Quantity", "Acquired", "Sold", "Proceeds", "Cost Basis", "Short-Term G/L", "Long-Term G/L", "Total Realized G/L", "Disallowed Loss", "Economic G/L", "Return %", "Tax Term", "Source Row"]
    write_headers(sheet, 3, headers, fmts)
    widths = [12,13,18,46,14,12,12,12,15,15,16,16,17,15,15,11,13,11]
    for col, width in enumerate(widths): sheet.set_column(col, col, width)
    sheet.set_row(3, 32)
    for row, lot in enumerate(report.lots, start=4):
        values = [lot.source_name, lot.account, lot.symbol, lot.description, lot.security_type, _number(lot.quantity), datetime.combine(lot.acquired_date, time.min), datetime.combine(lot.sale_date, time.min), _number(lot.proceeds_usd), _number(lot.cost_basis_usd), _number(lot.short_term_gain_loss_usd), _number(lot.long_term_gain_loss_usd), _number(lot.total_realized_gain_loss_usd), _number(lot.disallowed_loss_usd), None, None, lot.tax_term, lot.source_row]
        for col, value in enumerate(values):
            fmt = fmts["body"]
            if col == 3: fmt = fmts["text_wrap"]
            if col == 5: fmt = fmts["quantity"]
            if col in (6, 7): fmt = fmts["date"]
            if 8 <= col <= 13: fmt = fmts["currency"]
            if col == 17: fmt = fmts["count"]
            if col == 14: sheet.write_formula(row, col, f"=I{row+1}-J{row+1}", fmts["currency_formula"])
            elif col == 15: sheet.write_formula(row, col, f"=IFERROR(M{row+1}/J{row+1},0)", fmts["percent"])
            else: sheet.write(row, col, value, fmt)
    last = 4 + len(report.lots) - 1
    sheet.add_table(3, 0, last, 17, {"name": "RealizedLotsTable", "style": "Table Style Medium 2", "columns": [{"header": value} for value in headers]})
    sheet.conditional_format(4, 12, last, 12, {"type": "cell", "criteria": "<", "value": 0, "format": book.add_format({"font_color": "#B91C1C"})})
    sheet.conditional_format(4, 12, last, 12, {"type": "cell", "criteria": ">", "value": 0, "format": book.add_format({"font_color": "#15803D"})})
    return 5, last + 1


def _write_security(book, report, fmts, first, last):
    sheet = book.get_worksheet_by_name("Security Summary")
    write_title(sheet, "Realized Gain/Loss by Security", "Formula-driven rollup with separate short- and long-term transaction counts and gain/loss amounts.", 12, fmts)
    headers = ["Symbol", "Security Description", "Type", "Total Lots", "Short-Term Lots", "Long-Term Lots", "Proceeds", "Cost Basis", "Short-Term G/L", "Long-Term G/L", "Total Realized G/L", "Return %"]
    write_headers(sheet, 3, headers, fmts); sheet.set_row(3, 34)
    for col,width in enumerate([22,52,15,11,13,13,15,15,16,16,17,11]): sheet.set_column(col,col,width)
    securities = {}
    for lot in report.lots: securities.setdefault(lot.symbol, (lot.description, lot.security_type))
    for row, symbol in enumerate(sorted(securities, key=str.upper), start=4):
        desc, kind = securities[symbol]
        sheet.write(row, 0, symbol, fmts["body"]); sheet.write(row, 1, desc, fmts["text_wrap"]); sheet.write(row, 2, kind, fmts["body"])
        excel_row = row + 1
        formulas = [f"=COUNTIF('Realized Lots'!$C${first}:$C${last},A{excel_row})", f'=COUNTIFS(\'Realized Lots\'!$C${first}:$C${last},A{excel_row},\'Realized Lots\'!$Q${first}:$Q${last},"Short-Term")', f'=COUNTIFS(\'Realized Lots\'!$C${first}:$C${last},A{excel_row},\'Realized Lots\'!$Q${first}:$Q${last},"Long-Term")']
        for col, formula in enumerate(formulas, start=3): sheet.write_formula(row,col,formula,fmts["formula"] if col > 2 else fmts["count"])
        for col, source_col in zip(range(6,10), "IJKL"):
            sheet.write_formula(row,col,f"=SUMIF('Realized Lots'!$C${first}:$C${last},A{excel_row},'Realized Lots'!${source_col}${first}:${source_col}${last})",fmts["currency_formula"])
        sheet.write_formula(row,10,f"=I{excel_row}+J{excel_row}",fmts["currency_formula"]); sheet.write_formula(row,11,f"=IFERROR(K{excel_row}/H{excel_row},0)",fmts["percent"])
    last_row = 4 + len(securities) - 1
    sheet.add_table(3,0,last_row,11,{"name":"SecuritySummaryTable","style":"Table Style Medium 2","columns":[{"header": value} for value in headers]})
    for col in (6,8,9,10):
        sheet.conditional_format(4,col,last_row,col,{"type":"cell","criteria":"<","value":0,"format":book.add_format({"font_color":"#B91C1C"})})
        sheet.conditional_format(4,col,last_row,col,{"type":"cell","criteria":">","value":0,"format":book.add_format({"font_color":"#15803D"})})
    return 5, last_row + 1


def _write_checks(book, report, fmts, first, last, security_first, security_last):
    sheet = book.get_worksheet_by_name("Checks")
    write_title(sheet, "Audit Checks", "Each check reconciles the consolidated report to the supplied source records.", 7, fmts)
    headers=["Check","Actual","Expected","Difference","Tolerance","Status","Notes"]; write_headers(sheet,3,headers,fmts)
    source_sum = "+".join(f"'Source Notes'!$C${row}" for row in range(4,4+len(report.sources)))
    checks=[("Transaction count",f"=COUNTA('Realized Lots'!$A${first}:$A${last})",f"={source_sum}",0,"Consolidated lots equal the source record counts."),("Reported G/L reconciliation",f"=SUM('Realized Lots'!$M${first}:$M${last})",f"=SUM('Realized Lots'!$I${first}:$I${last})-SUM('Realized Lots'!$J${first}:$J${last})+SUM('Realized Lots'!$N${first}:$N${last})",.01,"Reported G/L = proceeds − basis + disallowed loss."),("Short + long-term tie-out",f"=SUM('Realized Lots'!$K${first}:$K${last})+SUM('Realized Lots'!$L${first}:$L${last})",f"=SUM('Realized Lots'!$M${first}:$M${last})",.01,"Tax-term components equal total reported G/L."),(f"{report.report_year} sale dates",f'=COUNTIFS(\'Realized Lots\'!$H${first}:$H${last},">="&DATE({report.report_year},1,1),\'Realized Lots\'!$H${first}:$H${last},"<"&DATE({report.report_year+1},1,1))',f"=COUNTA('Realized Lots'!$A${first}:$A${last})",0,f"All included lots have {report.report_year} sale dates."),("Missing proceeds/basis",f"=COUNTBLANK('Realized Lots'!$I${first}:$I${last})+COUNTBLANK('Realized Lots'!$J${first}:$J${last})",0,0,"No blank proceeds or cost-basis cells.")]
    for row, source in enumerate(report.sources, start=4): checks.append((f"{source.source_name} source count",f'=COUNTIF(\'Realized Lots\'!$A${first}:$A${last},"{source.source_name}")',f"='Source Notes'!$C${row}",0,f"{source.source_name} normalized rows equal {source.source_name} export records."))
    checks.extend([("Security short-term summary tie-out",f"=SUM('Security Summary'!$I${security_first}:$I${security_last})",f"=SUM('Realized Lots'!$K${first}:$K${last})",.01,"Security Summary short-term G/L equals the lot-level short-term total."),("Security long-term summary tie-out",f"=SUM('Security Summary'!$J${security_first}:$J${security_last})",f"=SUM('Realized Lots'!$L${first}:$L${last})",.01,"Security Summary long-term G/L equals the lot-level long-term total."),("Security term total tie-out",f"=SUM('Security Summary'!$K${security_first}:$K${security_last})",f"=SUM('Security Summary'!$I${security_first}:$I${security_last})+SUM('Security Summary'!$J${security_first}:$J${security_last})",.01,"Security Summary total G/L equals short-term plus long-term columns."),("Realized Lots numeric field types",f"=COUNT('Realized Lots'!$F${first}:$P${last})+COUNT('Realized Lots'!$R${first}:$R${last})",f"=COUNTA('Realized Lots'!$F${first}:$P${last})+COUNTA('Realized Lots'!$R${first}:$R${last})",0,"All populated quantity, date, amount, return, and source-row cells are true numeric/date values."),("Security Summary numeric field types",f"=COUNT('Security Summary'!$D${security_first}:$L${security_last})",f"=COUNTA('Security Summary'!$D${security_first}:$L${security_last})",0,"All populated count, amount, and return formula cells are numeric so Excel sorts them by value.")])
    for row,(label,actual,expected,tolerance,note) in enumerate(checks,start=4):
        money = "G/L" in label or "Security" in label
        value_fmt=fmts["currency_formula"] if money else fmts["formula"]
        sheet.write(row,0,label,fmts["body"]); sheet.write_formula(row,1,actual,value_fmt); sheet.write_formula(row,2,expected,value_fmt) if isinstance(expected,str) and expected.startswith("=") else sheet.write(row,2,expected,fmts["currency"] if money else fmts["count"])
        diff=f"=ROUND(B{row+1}-C{row+1},2)" if row+1 in (12,13,14) else f"=B{row+1}-C{row+1}"
        sheet.write_formula(row,3,diff,fmts["currency_formula"] if money else fmts["formula"]); sheet.write(row,4,tolerance,fmts["currency"] if money else fmts["count"]); sheet.write_formula(row,5,f'=IF(ABS(D{row+1})<=E{row+1},"OK","REVIEW")',fmts["formula"]); sheet.write(row,6,note,fmts["text_wrap"])
    last_row=4+len(checks)-1; sheet.add_table(3,0,last_row,6,{"name":"AuditChecksTable","style":"Table Style Medium 2","columns":[{"header":x} for x in headers]})
    sheet.merge_range(last_row+2,0,last_row+2,6,"Model Status",fmts["legend"]); sheet.write(last_row+3,0,"Overall",fmts["body"]); sheet.write_formula(last_row+3,1,f'=IF(COUNTIF(F5:F{last_row+1},"REVIEW")=0,"OK","REVIEW")',fmts["formula"])
    for col,width in enumerate([38,16,16,16,13,13,68]): sheet.set_column(col,col,width)
    return last_row+4


def _write_summary(book, report, fmts, first, last, status_row):
    sheet=book.get_worksheet_by_name("Summary"); sources=" and ".join(sorted({lot.source_name for lot in report.lots}))
    write_title(sheet,f"{report.report_year} Realized Investment Gain/Loss Report",f"Consolidated from {sources} exports • USD • Sales through {max(l.sale_date for l in report.lots):%Y-%m-%d} • Prepared {datetime.now():%Y-%m-%d}",12,fmts)
    kpis=[("Total Realized G/L",f"=SUM('Realized Lots'!$M${first}:$M${last})"),("Short-Term G/L",f"=SUM('Realized Lots'!$K${first}:$K${last})"),("Long-Term G/L",f"=SUM('Realized Lots'!$L${first}:$L${last})"),("Proceeds",f"=SUM('Realized Lots'!$I${first}:$I${last})"),("Cost Basis",f"=SUM('Realized Lots'!$J${first}:$J${last})"),("Disallowed Loss",f"=SUM('Realized Lots'!$N${first}:$N${last})")]
    for col,(label,formula) in enumerate(kpis): sheet.write(3,col,label,fmts["kpi_label"]); sheet.write_formula(4,col,formula,fmts["kpi"])
    sheet.set_row(4,34); sheet.merge_range(3,8,3,11,"Audit status",fmts["audit_label"]); sheet.merge_range(4,8,4,11,"",fmts["audit_status"]); sheet.write_formula(4,8,f"='Checks'!$B${status_row}",fmts["audit_status"])
    accounts=sorted({(lot.account,lot.source_name) for lot in report.lots},reverse=True); sheet.merge_range(7,0,7,6,"By account",fmts["section"]); sheet.merge_range(7,8,7,10,"By tax term",fmts["section"])
    account_headers=["Account","Source","Proceeds","Cost Basis","Short-Term G/L","Long-Term G/L","Total G/L"]; write_headers(sheet,8,account_headers,fmts)
    for row,(account,source) in enumerate(accounts,start=9):
        sheet.write(row,0,account,fmts["body"]); sheet.write(row,1,source,fmts["body"])
        for col,source_col in zip(range(2,7),"IJKLM"): sheet.write_formula(row,col,f"=SUMIFS('Realized Lots'!${source_col}${first}:${source_col}${last},'Realized Lots'!$A${first}:$A${last},B{row+1},'Realized Lots'!$B${first}:$B${last},A{row+1})",fmts["whole_formula"])
    total_row=9+len(accounts); sheet.write(total_row,0,"Total",fmts["total"])
    for col in range(2,7): sheet.write_formula(total_row,col,f"=SUM({xl_col_to_name(col)}10:{xl_col_to_name(col)}{total_row})",fmts["total_whole"])
    write_headers(sheet,8,["Tax Term","Gain/Loss","% of Total"],fmts,start_column=8)
    for row,(term,kpi_col) in enumerate((("Short-Term","B"),("Long-Term","C")),start=9): sheet.write(row,8,term,fmts["body"]); sheet.write_formula(row,9,f"={kpi_col}5",fmts["whole_formula"]); sheet.write_formula(row,10,f"=IFERROR(J{row+1}/$A$5,0)",fmts["percent"])
    sheet.write(total_row,8,"Total",fmts["total"]); sheet.write_formula(total_row,9,"=SUM(J10:J11)",fmts["total_whole"]); sheet.write_formula(total_row,10,"=SUM(K10:K11)",fmts["percent"])
    write_headers(sheet,33,["Month","Short-Term G/L","Long-Term G/L"],fmts)
    final_month=max(lot.sale_date.month for lot in report.lots)
    for month in range(1,final_month+1):
        row=33+month; sheet.write(row,0,f"{datetime(report.report_year,month,1):%b %Y}",fmts["body"]); next_year=report.report_year+(month==12); next_month=1 if month==12 else month+1
        for col,source_col in ((1,"K"),(2,"L")): sheet.write_formula(row,col,f'=SUMIFS(\'Realized Lots\'!${source_col}${first}:${source_col}${last},\'Realized Lots\'!$H${first}:$H${last},">="&DATE({report.report_year},{month},1),\'Realized Lots\'!$H${first}:$H${last},"<"&DATE({next_year},{next_month},1))',fmts["whole_formula"])
    sheet.merge_range(33,4,33,7,"Workbook legend",fmts["legend"]); sheet.write(34,4,"Green text",fmts["green"]); sheet.write(34,5,"Cross-sheet linked formulas",fmts["body"]); sheet.write(35,4,"Black text",fmts["body"]); sheet.write(35,5,"Imported source data / calculations",fmts["body"]); sheet.merge_range(38,4,40,11,"Planning note: This report summarizes brokerage-export data and is not tax advice. Verify final figures against year-end Forms 1099-B and brokerage statements; wash-sale adjustments may change before year-end.",fmts["note"])
    for col,width in enumerate([17,17,17,17,17,17,17,3,17,17,17,17]): sheet.set_column(col,col,width)
    add_account_gain_chart(book, sheet, total_row)
    add_monthly_gain_chart(book, sheet, final_month)


def _write_source_notes(book, report, fmts):
    sheet=book.get_worksheet_by_name("Source Notes"); write_title(sheet,"Source Notes & Reporting Conventions","",6,fmts); sheet.set_row(1,None)
    headers=["Source","File","Records","Earliest Sale","Latest Sale","Notes"]; write_headers(sheet,2,headers,fmts)
    for row,source in enumerate(report.sources,start=3):
        sheet.write(row,0,source.source_name,fmts["body"]); sheet.write(row,1,source.source_file,fmts["text_wrap"]); sheet.write(row,2,source.included_rows,fmts["count"]); sheet.write_datetime(row,3,datetime.combine(source.earliest_sale,time.min),fmts["date"]); sheet.write_datetime(row,4,datetime.combine(source.latest_sale,time.min),fmts["date"]); sheet.write(row,5,source.notes,fmts["text_wrap"]); sheet.set_row(row,42)
    section=3+len(report.sources)+1; sheet.merge_range(section,0,section,5,"Reporting conventions",fmts["legend"])
    conventions=[("Currency","USD"),("Period",f"{report.report_year} sale dates contained in the provided exports"),("Total realized G/L","Short-term G/L + long-term G/L, as reported by each export"),("Economic G/L","Proceeds − cost basis"),("Wash-sale treatment","Disallowed loss is shown separately and explains the difference between reported and economic G/L"),("Use","Planning and review only; verify against year-end Forms 1099-B, account statements, and a tax professional")]
    for offset,(label,value) in enumerate(conventions,start=1): sheet.write(section+offset,0,label,book.add_format({"font_name":"Aptos","font_size":10,"bold":True,"font_color":"#15324B"})); sheet.write(section+offset,1,value,fmts["text_wrap"])
    note=section+len(conventions)+2; sheet.merge_range(note,0,note+1,5,"Important: This workbook summarizes the supplied exports; it is not tax advice and does not replace official tax forms or brokerage statements.",fmts["note"]); sheet.set_row(note,38); sheet.set_row(note+1,38)
    for col,width in enumerate([22,50,12,14,14,54]): sheet.set_column(col,col,width)
