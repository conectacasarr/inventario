def exportar_pdf(itens, transacoes, emprestimos, filtro_tipo, filtro_grupo, filtro_data_inicio, filtro_data_fim):
    # Criar PDF com ReportLab
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    
    # Título
    elements.append(Paragraph("Relatório de Inventário", styles["Title"]))
    elements.append(Spacer(1, 0.2*inch))
    
    # Informações do filtro
    filtro_info = []
    if filtro_grupo:
        filtro_info.append(f"Grupo: {filtro_grupo}")
    if filtro_tipo != "todos":
        filtro_info.append(f"Tipo: {filtro_tipo.capitalize()}")
    if filtro_data_inicio:
        filtro_info.append(f"Data Início: {format_date(filtro_data_inicio)}")
    if filtro_data_fim:
        filtro_info.append(f"Data Fim: {format_date(filtro_data_fim)}")
    
    if filtro_info:
        elements.append(Paragraph("<i>Filtros aplicados:</i> " + ", ".join(filtro_info), styles["Italic"]))
        elements.append(Spacer(1, 0.1*inch))
    
    # Estilo de tabela padrão
    table_style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4), # Padding reduzido
        ("FONTSIZE", (0, 0), (-1, -1), 8), # Fonte menor
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), # Cabeçalho em negrito
    ])
    
    # Exportar itens (sempre exporta se houver itens)
    if itens:
        elements.append(Paragraph("<b>INVENTÁRIO - ITENS</b>", styles["Heading2"]))
        data_itens_pdf = [["Tombamento", "Descrição", "Grupo", "Marca", "Valor", "Qtd"]]
        
        for item in itens:
            data_itens_pdf.append([
                item["tombamento"],
                Paragraph(item["descricao"], styles["Normal"]), # Permitir quebra de linha
                item["grupo"] or "",
                item["marca"] or "",
                f"R$ {item['valor']:.2f}".replace(".", ",") if item["valor"] is not None else "-",
                str(item["quantidade"])
            ])
        
        # Ajustar larguras das colunas
        t_itens = Table(data_itens_pdf, colWidths=[0.8*inch, 2.5*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.5*inch])
        t_itens.setStyle(table_style)
        elements.append(t_itens)
        elements.append(Spacer(1, 0.2*inch))
    
    # Exportar transações
    if transacoes and filtro_tipo in ["todos", "transacoes"]:
        elements.append(Paragraph("<b>TRANSAÇÕES</b>", styles["Heading2"]))
        data_transacoes_pdf = [["Data", "Tipo", "Item (Tomb.)", "Descrição", "Qtd", "Usuário"]]
        
        for t in transacoes:
            data_transacoes_pdf.append([
                format_date(t["data"]),
                t["tipo"],
                t["tombamento"],
                Paragraph(t["descricao"], styles["Normal"]), # Permitir quebra de linha
                str(t["quantidade"]),
                t["usuario_nome"]
            ])
        
        t_trans = Table(data_transacoes_pdf, colWidths=[0.8*inch, 0.6*inch, 0.8*inch, 2.5*inch, 0.5*inch, 1*inch])
        t_trans.setStyle(table_style)
        elements.append(t_trans)
        elements.append(Spacer(1, 0.2*inch))
    
    # Exportar empréstimos
    if emprestimos and filtro_tipo in ["todos", "emprestimos"]:
        elements.append(Paragraph("<b>EMPRÉSTIMOS</b>", styles["Heading2"]))
        # Ajuste no cabeçalho e colunas para melhor espaçamento
        data_emprestimos_pdf = [["Data Emp.", "Data Dev.", "Item (Tomb.)", "Descrição", "Qtd", "Responsável", "Status"]]
        
        for e in emprestimos:
            # Separar os dados concatenados em listas
            tombamentos = e["tombamentos"].split(", ") if e["tombamentos"] else []
            descricoes = e["descricoes"].split(", ") if e["descricoes"] else []
            quantidades = e["quantidades"].split(", ") if e["quantidades"] else []
            
            # Garantir que todas as listas tenham o mesmo tamanho
            max_itens = max(len(tombamentos), len(descricoes), len(quantidades))
            
            # Se não houver itens, adicionar uma linha vazia
            if max_itens == 0:
                data_emprestimos_pdf.append([
                    format_date(e["data_emprestimo"]),
                    format_date(e["data_devolucao"]) if e["data_devolucao"] else "-",
                    "-",
                    "-",
                    "-",
                    f"{e['nome']} {e['sobrenome']}",
                    "Devolvido" if e["data_devolucao"] else "Ativo"
                ])
            else:
                # Para cada item do empréstimo, adicionar uma linha
                for i in range(max_itens):
                    tombamento = tombamentos[i] if i < len(tombamentos) else "-"
                    descricao = descricoes[i] if i < len(descricoes) else "-"
                    quantidade = quantidades[i] if i < len(quantidades) else "-"
                    
                    # Apenas na primeira linha do empréstimo, mostrar as datas e o responsável
                    if i == 0:
                        data_emprestimos_pdf.append([
                            format_date(e["data_emprestimo"]),
                            format_date(e["data_devolucao"]) if e["data_devolucao"] else "-",
                            tombamento,
                            Paragraph(descricao, styles["Normal"]),
                            quantidade,
                            f"{e['nome']} {e['sobrenome']}",
                            "Devolvido" if e["data_devolucao"] else "Ativo"
                        ])
                    else:
                        # Nas linhas subsequentes, repetir apenas os dados do item
                        data_emprestimos_pdf.append([
                            "",
                            "",
                            tombamento,
                            Paragraph(descricao, styles["Normal"]),
                            quantidade,
                            "",
                            ""
                        ])
        
        # Ajustar larguras das colunas para evitar sobreposição
        t_emp = Table(data_emprestimos_pdf, colWidths=[0.7*inch, 0.7*inch, 0.8*inch, 2.0*inch, 0.4*inch, 1.2*inch, 0.7*inch])
        t_emp.setStyle(table_style)
        elements.append(t_emp)
    
    # Rodapé
    def add_footer(canvas, doc):
        canvas.saveState()
        styles = getSampleStyleSheet()
        footer_text = f"OAIBV – Organização e Apoio à Igreja em Boa Vista | Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Página %d" % doc.page
        p = Paragraph(footer_text, styles["Normal"]) # Use Normal style, adjust size if needed
        w, h = p.wrap(doc.width, doc.bottomMargin)
        p.drawOn(canvas, doc.leftMargin, h)
        canvas.restoreState()
    
    # Construir o documento com o rodapé
    doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
    buffer.seek(0)
    
    # Retornar o PDF como resposta para download
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mimetype="application/pdf"
    )
