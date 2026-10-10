import os
import datetime
from typing import List, Dict, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def generate_pdf_report(user_info: Dict[str, Any], trades: List[Any], stats: Dict[str, Any], output_path: str) -> bool:
    """Generate a PDF Trading Journal Report."""
    try:
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )
        story = []
        styles = getSampleStyleSheet()

        # Custom Styles
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=22,
            textColor=colors.HexColor('#0F172A'),
            spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            'DocSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            textColor=colors.HexColor('#64748B'),
            spaceAfter=15
        )
        section_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            textColor=colors.HexColor('#1E293B'),
            spaceBefore=15,
            spaceAfter=8
        )
        cell_style = ParagraphStyle(
            'CellText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            textColor=colors.HexColor('#334155'),
            alignment=1 # Center
        )
        header_cell_style = ParagraphStyle(
            'HeaderCellText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            textColor=colors.white,
            alignment=1
        )

        # Header Title
        trader_name = user_info.get("first_name") or user_info.get("username") or "Trader"
        date_str = datetime.datetime.now().strftime("%B %d, %Y")
        story.append(Paragraph(f"FXDiary Trading Performance Report", title_style))
        story.append(Paragraph(f"Account: <b>{trader_name}</b> | Generated on: {date_str} | Total Trades: {stats['total_trades']}", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=15))

        # 4 Key Metrics Cards Table
        pnl_val = stats['total_net_pnl']
        pnl_color = "#10B981" if pnl_val >= 0 else "#EF4444"
        pnl_sign = "+" if pnl_val >= 0 else ""

        cards_data = [
            [
                Paragraph("<font color='#64748B' size=8>NET PROFIT/LOSS</font><br/><font size=14 color='%s'><b>%s$%s</b></font>" % (pnl_color, pnl_sign, f"{abs(pnl_val):,.2f}"), styles['Normal']),
                Paragraph("<font color='#64748B' size=8>WIN RATE</font><br/><font size=14 color='#3B82F6'><b>%s%%</b></font>" % stats['win_rate'], styles['Normal']),
                Paragraph("<font color='#64748B' size=8>PROFIT FACTOR</font><br/><font size=14 color='#8B5CF6'><b>%s</b></font>" % stats['profit_factor'], styles['Normal']),
                Paragraph("<font color='#64748B' size=8>TOTAL TRADES</font><br/><font size=14 color='#0F172A'><b>%s</b></font>" % stats['total_trades'], styles['Normal']),
            ]
        ]
        cards_table = Table(cards_data, colWidths=[130, 130, 130, 130])
        cards_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
            ('INNERGRID', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(cards_table)
        story.append(Spacer(1, 15))

        # Secondary Stats Table
        sec_stats = [
            ["Wins", str(stats['wins']), "Avg Win", f"${stats['avg_win']:,.2f}", "Best Trade", f"${stats['best_trade']:,.2f}"],
            ["Losses", str(stats['losses']), "Avg Loss", f"${stats['avg_loss']:,.2f}", "Worst Trade", f"${stats['worst_trade']:,.2f}"],
            ["Break Even", str(stats['breakeven']), "Max Drawdown", f"${stats['max_drawdown']:,.2f}", "Total Pips", f"{stats['total_pips']} pips"]
        ]
        sec_table = Table(sec_stats, colWidths=[90, 80, 90, 80, 90, 90])
        sec_table.setStyle(TableStyle([
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#334155')),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTNAME', (4,0), (4,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#F1F5F9')),
        ]))
        story.append(sec_table)
        story.append(Spacer(1, 15))

        # Trade History Table Title
        story.append(Paragraph("Trade Log History", section_style))

        # Trade History Table Data
        table_headers = ["Date & Time", "Ticket", "Symbol", "Type", "Lots", "Open", "Close", "Pips", "Net PnL"]
        table_rows = [[Paragraph(h, header_cell_style) for h in table_headers]]

        for t in trades[:100]: # Limit top 100 in PDF
            close_time = t.close_time.strftime("%Y-%m-%d %H:%M") if hasattr(t, "close_time") and t.close_time else "-"
            ticket = t.ticket if hasattr(t, "ticket") and t.ticket else "-"
            sym = t.symbol.upper() if hasattr(t, "symbol") else t.get("symbol", "-")
            ttype = t.trade_type.upper() if hasattr(t, "trade_type") else t.get("trade_type", "-")
            lots = f"{t.volume:.2f}" if hasattr(t, "volume") else f"{t.get('volume', 0.01):.2f}"
            open_p = f"{t.open_price:.5f}" if hasattr(t, "open_price") else f"{t.get('open_price', 0):.5f}"
            close_p = f"{t.close_price:.5f}" if hasattr(t, "close_price") else f"{t.get('close_price', 0):.5f}"
            pips = f"{t.pips:.1f}" if hasattr(t, "pips") else f"{t.get('pips', 0):.1f}"
            pnl = t.net_profit if hasattr(t, "net_profit") else t.get("net_profit", 0.0)

            pnl_txt_color = "#15803D" if pnl > 0 else ("#B91C1C" if pnl < 0 else "#334155")
            pnl_formatted = f"<font color='{pnl_txt_color}'><b>${pnl:+,.2f}</b></font>"

            table_rows.append([
                Paragraph(close_time, cell_style),
                Paragraph(ticket, cell_style),
                Paragraph(sym, cell_style),
                Paragraph(ttype, cell_style),
                Paragraph(lots, cell_style),
                Paragraph(open_p, cell_style),
                Paragraph(close_p, cell_style),
                Paragraph(pips, cell_style),
                Paragraph(pnl_formatted, cell_style),
            ])

        history_table = Table(table_rows, colWidths=[90, 55, 55, 45, 40, 60, 60, 45, 70])
        history_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E293B')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')])
        ]))

        story.append(history_table)
        doc.build(story)
        return True
    except Exception as e:
        print(f"PDF Generation Error: {e}")
        return False

def generate_excel_report(user_info: Dict[str, Any], trades: List[Any], stats: Dict[str, Any], output_path: str) -> bool:
    """Generate an Excel Trading Journal Workbook."""
    try:
        wb = openpyxl.Workbook()
        
        # Sheet 1: Summary Dashboard
        ws_sum = wb.active
        ws_sum.title = "Summary & Analytics"
        ws_sum.views.sheetView[0].showGridLines = True

        title_font = Font(name="Calibri", size=16, bold=True, color="1E293B")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        bold_font = Font(name="Calibri", size=11, bold=True)
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        card_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        ws_sum.cell(row=2, column=2, value="FXDiary Trading Performance Summary").font = title_font
        ws_sum.cell(row=3, column=2, value=f"Account: {user_info.get('first_name', 'Trader')} | Date: {datetime.datetime.now().strftime('%Y-%m-%d')}")

        summary_metrics = [
            ("Total Net PnL", stats["total_net_pnl"]),
            ("Win Rate (%)", f"{stats['win_rate']}%"),
            ("Profit Factor", stats["profit_factor"]),
            ("Total Trades", stats["total_trades"]),
            ("Wins", stats["wins"]),
            ("Losses", stats["losses"]),
            ("Gross Profit", stats["gross_profit"]),
            ("Gross Loss", stats["gross_loss"]),
            ("Average Win", stats["avg_win"]),
            ("Average Loss", stats["avg_loss"]),
            ("Max Drawdown", stats["max_drawdown"]),
            ("Best Symbol", stats["best_symbol"])
        ]

        ws_sum.cell(row=5, column=2, value="Metric").font = header_font
        ws_sum.cell(row=5, column=2).fill = header_fill
        ws_sum.cell(row=5, column=3, value="Value").font = header_font
        ws_sum.cell(row=5, column=3).fill = header_fill

        for idx, (k, v) in enumerate(summary_metrics, start=6):
            ws_sum.cell(row=idx, column=2, value=k).font = bold_font
            ws_sum.cell(row=idx, column=3, value=v)
            ws_sum.cell(row=idx, column=2).border = thin_border
            ws_sum.cell(row=idx, column=3).border = thin_border

        # Sheet 2: Trade History Log
        ws_log = wb.create_sheet(title="Trade Log")
        ws_log.views.sheetView[0].showGridLines = True

        headers = [
            "Close Date", "Ticket", "Symbol", "Type", "Lots",
            "Open Price", "Close Price", "SL", "TP", "Pips",
            "Gross Profit", "Swap", "Commission", "Net PnL", "Status"
        ]

        for col_num, header in enumerate(headers, 1):
            cell = ws_log.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        green_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        red_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

        for row_idx, t in enumerate(trades, start=2):
            close_time = t.close_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(t, "close_time") and t.close_time else ""
            ticket = t.ticket if hasattr(t, "ticket") and t.ticket else "-"
            sym = t.symbol.upper() if hasattr(t, "symbol") else t.get("symbol", "-")
            ttype = t.trade_type.upper() if hasattr(t, "trade_type") else t.get("trade_type", "-")
            lots = t.volume if hasattr(t, "volume") else t.get("volume", 0.01)
            open_p = t.open_price if hasattr(t, "open_price") else t.get("open_price", 0.0)
            close_p = t.close_price if hasattr(t, "close_price") else t.get("close_price", 0.0)
            sl = t.sl if hasattr(t, "sl") else t.get("sl")
            tp = t.tp if hasattr(t, "tp") else t.get("tp")
            pips = t.pips if hasattr(t, "pips") else t.get("pips", 0.0)
            profit = t.profit if hasattr(t, "profit") else t.get("profit", 0.0)
            swap = t.swap if hasattr(t, "swap") else t.get("swap", 0.0)
            comm = t.commission if hasattr(t, "commission") else t.get("commission", 0.0)
            net_pnl = t.net_profit if hasattr(t, "net_profit") else t.get("net_profit", 0.0)
            status = "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BE")

            row_vals = [
                close_time, ticket, sym, ttype, lots,
                open_p, close_p, sl or "-", tp or "-", pips,
                profit, swap, comm, net_pnl, status
            ]

            for col_idx, val in enumerate(row_vals, start=1):
                c = ws_log.cell(row=row_idx, column=col_idx, value=val)
                c.border = thin_border
                c.alignment = Alignment(horizontal="center")
                
                # Highlight PnL column
                if col_idx == 14 or col_idx == 15:
                    if net_pnl > 0:
                        c.fill = green_fill
                    elif net_pnl < 0:
                        c.fill = red_fill

        # Auto-adjust column widths
        for ws in [ws_sum, ws_log]:
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(output_path)
        return True
    except Exception as e:
        print(f"Excel Generation Error: {e}")
        return False
