import os
import re
import xml.etree.ElementTree as ET
from fpdf import FPDF

# Helper to find tag case-insensitive and namespace-insensitive
def find_elem_insensitive(parent, tag_name):
    target = tag_name.lower()
    for elem in parent.iter():
        clean_tag = elem.tag.split('}', 1)[1] if '}' in elem.tag else elem.tag
        if clean_tag.lower() == target:
            return elem
    return None

def sanitize_pdf_text(text):
    if not text:
        return ""
    text_str = str(text)
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
        "\xa0": " ",
        "\u200b": "",
    }
    for old, new in replacements.items():
        text_str = text_str.replace(old, new)
    return text_str.encode("latin-1", errors="replace").decode("latin-1")

def get_xml_val(root, candidates, parent_tags=None):
    if parent_tags:
        for p_tag in parent_tags:
            p_elem = find_elem_insensitive(root, p_tag)
            if p_elem is not None:
                for c in candidates:
                    elem = find_elem_insensitive(p_elem, c)
                    if elem is not None and elem.text:
                        return elem.text.strip()
    for c in candidates:
        elem = find_elem_insensitive(root, c)
        if elem is not None and elem.text:
            return elem.text.strip()
    return ""

def parse_localized_float(val):
    if not val:
        return 0.0
    val_str = str(val).replace("R$", "").replace(" ", "").strip()
    if not val_str or val_str == "-":
        return 0.0
        
    # If both , and . are present
    if "," in val_str and "." in val_str:
        if val_str.index(".") < val_str.index(","):
            # e.g. 1.234,56 -> 1234.56
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            # e.g. 1,234.56 -> 1234.56
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        # Only comma is present.
        parts = val_str.split(",")
        if len(parts[-1]) == 3:
            # Thousands separator, e.g. 350,000 -> 350000
            val_str = val_str.replace(",", "")
        else:
            # Decimal separator, e.g. 350,00 -> 350.00
            val_str = val_str.replace(",", ".")
    elif "." in val_str:
        # Only dot is present.
        parts = val_str.split(".")
        if len(parts[-1]) == 3:
            # Thousands separator, e.g. 350.000 -> 350000
            val_str = val_str.replace(".", "")
            
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def format_currency(val):
    if not val or val == "-":
        return "-"
    float_val = parse_localized_float(val)
    if float_val == 0.0:
        # Check if the string was actually zero or invalid
        clean = str(val).replace("R$", "").replace(" ", "").replace(",", ".").strip()
        try:
            if float(clean) == 0.0:
                return "R$ 0,00"
        except ValueError:
            pass
        return "-"
    return f"R$ {float_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_cnpj(val):
    if not val or val == "-":
        return "-"
    digits = re.sub(r'\D', '', str(val))
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    elif len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return val

def format_cep(val):
    if not val or val == "-":
        return "-"
    digits = re.sub(r'\D', '', str(val))
    if len(digits) == 8:
        return f"{digits[:5]}-{digits[5:]}"
    return val

def parse_xml_for_pdf(filepath):
    data = {
        # Identificação
        "numero_nf": "-",
        "competencia": "-",
        "data_emissao": "-",
        "chave_acesso": "-",
        "numero_dps": "-",
        "serie_dps": "-",
        "data_dps": "-",
        
        # Prestador
        "prestador_cnpj": "-",
        "prestador_im": "-",
        "prestador_fone": "-",
        "prestador_nome": "-",
        "prestador_email": "-",
        "prestador_endereco": "-",
        "prestador_municipio": "-",
        "prestador_uf": "-",
        "prestador_cep": "-",
        "prestador_simples": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)",
        "prestador_regime": "Regime de apuração do Simples Nacional",
        
        # Tomador
        "tomador_cnpj": "-",
        "tomador_im": "-",
        "tomador_fone": "-",
        "tomador_nome": "-",
        "tomador_email": "-",
        "tomador_endereco": "-",
        "tomador_municipio": "-",
        "tomador_uf": "-",
        "tomador_cep": "-",
        
        # Serviço
        "servico_codigo_nacional": "-",
        "servico_codigo_municipal": "-",
        "servico_local": "-",
        "servico_pais": "-",
        "servico_descricao": "-",
        
        # Tributação Municipal
        "valor_servico": "0,00",
        "desconto_incondicionado": "-",
        "deducoes": "-",
        "calculo_bm": "-",
        "bc_issqn": "0,00",
        "aliq_iss": "0,00%",
        "retencao_iss": "Não Retido",
        "iss_apurado": "R$ 0,00",
        "iss_retido": "-",
        "regime_especial": "Nenhum",
        
        # Tributação Federal
        "pis": "-",
        "cofins": "-",
        "csll": "-",
        "irrf": "-",
        "inss": "-",
        
        # Totais
        "retencoes_federais": "-",
        "valor_liquido": "0,00",
        
        # Outros
        "informacoes_complementares": "-",
        "municipio_emissor": "MUNICIPIO DE SANTA BARBARA DOESTE",
        "municipio_fone": "(19)3455-8281"
    }
    
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        root = ET.fromstring(content)
        
        # 1. Identificação
        val = get_xml_val(root, ['Numero', 'NumeroNfse', 'numero_nf', 'nNFS', 'NumeroNFS', 'numero_nfse'])
        if val: data["numero_nf"] = val
        
        val = get_xml_val(root, ['Competencia', 'data_cadastro', 'DataEmissao', 'data_emissao'])
        if val:
            m = re.search(r'(\d{2})/(\d{2})/(\d{4})', val)
            if m: data["competencia"] = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
            else:
                m2 = re.search(r'(\d{4})-(\d{2})-(\d{2})', val)
                if m2: data["competencia"] = f"{m2.group(3)}/{m2.group(2)}/{m2.group(1)}"
        
        val = get_xml_val(root, ['DataEmissao', 'data_emissao', 'data_cadastro'])
        if val: data["data_emissao"] = val
        
        val = get_xml_val(root, ['codigo', 'ChaveAcesso', 'ChaveAcessoNfse', 'CodigoVerificacao'])
        if val: data["chave_acesso"] = val
        
        val = get_xml_val(root, ['rps', 'NumeroRps', 'numero_dps', 'nDPS'])
        if val: data["numero_dps"] = val
        
        val = get_xml_val(root, ['serie_rps', 'SerieRps', 'serie_dps'])
        if val: data["serie_dps"] = val
        
        val = get_xml_val(root, ['data_rps', 'DataRps', 'data_dps', 'data_cadastro'])
        if val: data["data_dps"] = val
        
        # 2. Prestador
        parents_p = ['Prestador', 'PrestadorServico', 'IdentificacaoPrestador', 'Emit', 'Emitente']
        val = get_xml_val(root, ['CNPJ', 'Cnpj', 'CPF', 'Cpf', 'cnpj_cpf_prestador', 'cnpj_prestador'], parents_p)
        if val: data["prestador_cnpj"] = format_cnpj(val)
        
        val = get_xml_val(root, ['InscricaoMunicipal', 'Im', 'im_prestador'], parents_p)
        if val: data["prestador_im"] = val
        
        val = get_xml_val(root, ['Telefone', 'fone_prestador'], parents_p)
        if val: data["prestador_fone"] = val
        
        val = get_xml_val(root, ['RazaoSocial', 'Nome', 'razao_social_prestador', 'nome_prestador'], parents_p)
        if val: data["prestador_nome"] = val
        
        val = get_xml_val(root, ['Email', 'email_prestador'], parents_p)
        if val: data["prestador_email"] = val
        
        # Address parts for prestador
        end = get_xml_val(root, ['Endereco', 'Logradouro', 'endereco_prestador'], parents_p + ['Endereco'])
        num = get_xml_val(root, ['Numero', 'numero_ende_prestador'], parents_p + ['Endereco'])
        bair = get_xml_val(root, ['Bairro', 'bairro_prestador'], parents_p + ['Endereco'])
        addr_parts = [p for p in [end, num, bair] if p]
        if addr_parts: data["prestador_endereco"] = ", ".join(addr_parts)
        
        val = get_xml_val(root, ['cidade_prestador', 'Cidade', 'Municipio'])
        if val: data["prestador_municipio"] = val
        
        val = get_xml_val(root, ['uf_prestador', 'UF', 'Uf'])
        if val: data["prestador_uf"] = val
        
        val = get_xml_val(root, ['cep_prestador', 'CEP', 'Cep'])
        if val: data["prestador_cep"] = format_cep(val)
        
        # 3. Tomador
        parents_t = ['Tomador', 'TomadorServico', 'IdentificacaoTomador', 'Dest', 'Destinatario']
        val = get_xml_val(root, ['CNPJ', 'Cnpj', 'CPF', 'Cpf', 'cnpj_cpf_destinatario', 'cnpj_destinatario', 'cnpj_cpf_tomador', 'cnpj_tomador'], parents_t)
        if val: data["tomador_cnpj"] = format_cnpj(val)
        
        val = get_xml_val(root, ['InscricaoMunicipal', 'Im', 'im_destinatario', 'im_tomador'], parents_t)
        if val: data["tomador_im"] = val
        
        val = get_xml_val(root, ['Telefone', 'fone_destinatario', 'fone_tomador'], parents_t)
        if val: data["tomador_fone"] = val
        
        val = get_xml_val(root, ['RazaoSocial', 'Nome', 'razao_social_destinatario', 'nome_destinatario', 'razao_social_tomador', 'nome_tomador'], parents_t)
        if val: data["tomador_nome"] = val
        
        val = get_xml_val(root, ['Email', 'email_destinatario', 'email_tomador'], parents_t)
        if val: data["tomador_email"] = val
        
        # Address parts for tomador
        end = get_xml_val(root, ['Endereco', 'Logradouro', 'endereco_destinatario', 'endereco_tomador'], parents_t + ['Endereco'])
        num = get_xml_val(root, ['Numero', 'numero_ende_destinatario', 'numero_ende_tomador'], parents_t + ['Endereco'])
        bair = get_xml_val(root, ['Bairro', 'bairro_destinatario', 'bairro_tomador'], parents_t + ['Endereco'])
        addr_parts = [p for p in [end, num, bair] if p]
        if addr_parts: data["tomador_endereco"] = ", ".join(addr_parts)
        
        val = get_xml_val(root, ['cidade_destinatario', 'cidade_tomador', 'Cidade', 'Municipio'])
        if val: data["tomador_municipio"] = val
        
        val = get_xml_val(root, ['uf_destinatario', 'uf_tomador', 'UF', 'Uf'])
        if val: data["tomador_uf"] = val
        
        val = get_xml_val(root, ['cep_destinatario', 'cep_tomador', 'CEP', 'Cep'])
        if val: data["tomador_cep"] = format_cep(val)
        
        # 4. Serviço
        val = get_xml_val(root, ['id_codigo_servico', 'CodigoTributacaoNacional', 'CodigoServico', 'item_lista_servico'])
        if val: data["servico_codigo_nacional"] = val
        
        val = get_xml_val(root, ['CodigoTributacaoMunicipal', 'CodigoTributacao', 'codigo_tributacao'])
        if val: data["servico_codigo_municipal"] = val
        
        val = get_xml_val(root, ['cidade_local_prest', 'LocalPrestacao', 'cidade_prestacao'])
        if val: data["servico_local"] = val
        
        val = get_xml_val(root, ['descricao', 'Discriminacao', 'discriminacao_servico'])
        if val: data["servico_descricao"] = val
        
        # 5. Tributação Municipal
        val = get_xml_val(root, ['valor_servico', 'ValorServicos', 'ValorServico', 'valor_nf'])
        if val: data["valor_servico"] = format_currency(val)
        
        val = get_xml_val(root, ['desconto_incondicionado', 'DescontoIncondicionado'])
        if val: data["desconto_incondicionado"] = format_currency(val)
        
        val = get_xml_val(root, ['deducao', 'TotalDeducoes', 'ValorDeducoes'])
        if val: data["deducoes"] = format_currency(val)
        
        val = get_xml_val(root, ['bc_iss', 'base_calculo', 'BaseCalculo', 'valor_servico'])
        if val: data["bc_issqn"] = format_currency(val)
        
        val = get_xml_val(root, ['aliq_iss', 'Aliquota', 'aliq_issqn'])
        if val:
            try:
                float_aliq = float(val.replace("%", "").replace(",", "."))
                data["aliq_iss"] = f"{float_aliq:.2f}%".replace(".", ",")
            except ValueError:
                data["aliq_iss"] = val
                
        val = get_xml_val(root, ['valor_iss', 'ValorIss', 'iss_apurado'])
        if val: data["iss_apurado"] = format_currency(val)
        
        val = get_xml_val(root, ['iss_retido', 'IssRetido'])
        if val:
            if val.lower() in ['s', '1', 'true', 'sim']:
                data["retencao_iss"] = "Retido"
                data["iss_retido"] = data["iss_apurado"]
            else:
                data["retencao_iss"] = "Não Retido"
                data["iss_retido"] = "-"
                
        # 6. Tributação Federal
        val = get_xml_val(root, ['valor_pis', 'Pis', 'PIS'])
        if val and parse_localized_float(val) > 0: data["pis"] = format_currency(val)
        
        val = get_xml_val(root, ['valor_cofins', 'Cofins', 'COFINS'])
        if val and parse_localized_float(val) > 0: data["cofins"] = format_currency(val)
        
        val = get_xml_val(root, ['valor_csll', 'Csll', 'CSLL'])
        if val and parse_localized_float(val) > 0: data["csll"] = format_currency(val)
        
        val = get_xml_val(root, ['valor_irrf', 'Irrf', 'IRRF'])
        if val and parse_localized_float(val) > 0: data["irrf"] = format_currency(val)
        
        val = get_xml_val(root, ['valor_inss', 'Inss', 'INSS'])
        if val and parse_localized_float(val) > 0: data["inss"] = format_currency(val)
        
        # Calculate federal retentions
        tot_fed = 0.0
        for fed_key in ['valor_pis', 'valor_cofins', 'valor_csll', 'valor_irrf', 'valor_inss']:
            fed_val = get_xml_val(root, [fed_key.split('_')[1], fed_key])
            if fed_val:
                try: tot_fed += parse_localized_float(fed_val)
                except ValueError: pass
        if tot_fed > 0:
            data["retencoes_federais"] = f"R$ {tot_fed:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
        # Valor Líquido
        val_liq = 0.0
        val_serv = 0.0
        try:
            val_serv = parse_localized_float(get_xml_val(root, ['valor_servico', 'ValorServicos', 'valor_nf']))
            val_liq = val_serv - tot_fed
            # Deduct ISS if retido
            if data["retencao_iss"] == "Retido":
                iss_val_str = get_xml_val(root, ['valor_iss', 'ValorIss'])
                val_liq -= parse_localized_float(iss_val_str)
        except Exception:
            val_liq = val_serv
            
        data["valor_liquido"] = f"R$ {val_liq:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Complementary info
        val = get_xml_val(root, ['informacoes_complementares', 'infCpl', 'InformacoesComplementares'])
        if val: data["informacoes_complementares"] = val
        
        # Municipality emitter fallback based on simple city prestador lookup
        if data["prestador_municipio"] and data["prestador_municipio"] != "-":
            data["municipio_emissor"] = f"MUNICIPIO DE {data['prestador_municipio'].upper()}"
            
    except Exception as e:
        print(f"[pdf_generator] Error parsing XML for PDF layout: {e}")
        
    return data

class DANFSePDF(FPDF):
    def __init__(self, data):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.data = data
        self.set_margins(10, 10, 10)
        self.set_auto_page_break(False)
        
    def draw_box(self, x, y, w, h, title, content, align="L", is_bold=False, title_color=(80, 80, 80)):
        title = sanitize_pdf_text(title)
        content = sanitize_pdf_text(content)
        # Draw bounding rect
        self.set_draw_color(160, 160, 160)
        self.set_line_width(0.18)
        self.rect(x, y, w, h)
        
        # Label/Title (small, top left)
        self.set_font("Helvetica", "", 5.5)
        self.set_text_color(*title_color)
        self.set_xy(x + 1, y + 1)
        self.cell(w - 2, 2.5, title, border=0, ln=0)
        
        # Content (larger, below title)
        self.set_font("Helvetica", "B" if is_bold else "", 7.5)
        self.set_text_color(0, 0, 0)
        self.set_xy(x + 1, y + 3.5)
        self.cell(w - 2, h - 4.5, str(content), border=0, align=align)
        
    def draw_multiline_box(self, x, y, w, h, title, content, is_bold=False):
        title = sanitize_pdf_text(title)
        content = sanitize_pdf_text(content)
        self.set_draw_color(160, 160, 160)
        self.set_line_width(0.18)
        self.rect(x, y, w, h)
        
        # Title
        self.set_font("Helvetica", "", 5.5)
        self.set_text_color(80, 80, 80)
        self.set_xy(x + 1, y + 1)
        self.cell(w - 2, 2.5, title, border=0, ln=0)
        
        # Content
        self.set_font("Helvetica", "B" if is_bold else "", 7)
        self.set_text_color(0, 0, 0)
        self.set_xy(x + 1, y + 3.5)
        self.multi_cell(w - 2, 3, str(content), border=0)
        
    def draw_section_header(self, x, y, w, h, title):
        title = sanitize_pdf_text(title)
        self.set_fill_color(225, 230, 240)
        self.set_draw_color(160, 160, 160)
        self.set_line_width(0.18)
        self.rect(x, y, w, h, "FD")
        
        self.set_font("Helvetica", "B", 6)
        self.set_text_color(40, 50, 80)
        self.set_xy(x + 1.5, y)
        self.cell(w - 3, h, title, border=0, align="L")

    def build_invoice(self):
        self.add_page()
        
        # Margins & general setup
        # Row 1: Header (Height: 24mm)
        # Box 1: Emitter Municipality
        self.set_draw_color(160, 160, 160)
        self.rect(10, 8, 70, 24)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(0, 0, 0)
        self.set_xy(12, 10)
        self.cell(66, 4, self.data["municipio_emissor"], ln=1)
        self.set_font("Helvetica", "", 7)
        self.set_xy(12, 14)
        self.cell(66, 3.5, "Secretaria de Fazenda e Planejamento", ln=1)
        self.set_xy(12, 17.5)
        self.cell(66, 3.5, f"Telefone: {self.data['municipio_fone']}", ln=1)
        
        # Box 2: Title Block
        self.rect(80, 8, 60, 24)
        self.set_font("Helvetica", "B", 10)
        self.set_xy(80, 11)
        self.cell(60, 4.5, "DANFSe v1.0", align="C", ln=1)
        self.set_font("Helvetica", "", 7.5)
        self.set_xy(80, 16)
        self.cell(60, 3.5, "Documento Auxiliar da NFS-e", align="C", ln=1)
        
        # Box 3: Invoice Number / Date info
        self.rect(140, 8, 60, 24)
        self.draw_box(140, 8, 30, 8, "Número da NFS-e", self.data["numero_nf"], "C", True)
        self.draw_box(170, 8, 30, 8, "Competência da NFS-e", self.data["competencia"], "C")
        self.draw_box(140, 16, 60, 8, "Data e Hora da emissão da NFS-e", self.data["data_emissao"], "C")
        # Bottom of Box 3 (DPS details)
        self.draw_box(140, 24, 20, 8, "Número da DPS", self.data["numero_dps"], "C")
        self.draw_box(160, 24, 15, 8, "Série", self.data["serie_dps"], "C")
        self.draw_box(175, 24, 25, 8, "Data Emissão DPS", self.data["data_dps"][:10], "C")
        
        # Row 2: Chave de Acesso (Height: 10mm)
        chave_formatted = " ".join([self.data["chave_acesso"][i:i+4] for i in range(0, len(self.data["chave_acesso"]), 4)])
        self.draw_box(10, 33, 190, 10, "Chave de Acesso da NFS-e (Verificação de Autenticidade no Portal Nacional)", chave_formatted, "C", True)
        
        # --- Section: Emitente (Prestador) ---
        self.draw_section_header(10, 44, 190, 4, "EMITENTE DA NFS-e (PRESTADOR DO SERVIÇO)")
        self.draw_box(10, 48, 48, 8, "CNPJ / CPF / NIF", self.data["prestador_cnpj"])
        self.draw_box(58, 48, 32, 8, "Inscrição Municipal", self.data["prestador_im"])
        self.draw_box(90, 48, 30, 8, "Telefone", self.data["prestador_fone"])
        self.draw_box(120, 48, 80, 8, "E-mail", self.data["prestador_email"])
        
        self.draw_box(10, 56, 190, 8, "Nome / Nome Empresarial (Razão Social)", self.data["prestador_nome"], is_bold=True)
        
        # Combine address details
        prestador_cidade_uf = f"{self.data['prestador_municipio']} - {self.data['prestador_uf']}" if self.data['prestador_municipio'] != "-" else "-"
        self.draw_box(10, 64, 115, 8, "Endereço", self.data["prestador_endereco"])
        self.draw_box(125, 64, 45, 8, "Município", prestador_cidade_uf)
        self.draw_box(170, 64, 30, 8, "CEP", self.data["prestador_cep"])
        
        self.draw_box(10, 72, 95, 8, "Simples Nacional na Data de Competência", self.data["prestador_simples"])
        self.draw_box(105, 72, 95, 8, "Regime de Apuração Tributária pelo SN", self.data["prestador_regime"])
        
        # --- Section: Tomador ---
        self.draw_section_header(10, 81, 190, 4, "TOMADOR DO SERVIÇO")
        self.draw_box(10, 85, 48, 8, "CNPJ / CPF / NIF", self.data["tomador_cnpj"])
        self.draw_box(58, 85, 32, 8, "Inscrição Municipal", self.data["tomador_im"])
        self.draw_box(90, 85, 30, 8, "Telefone", self.data["tomador_fone"])
        self.draw_box(120, 85, 80, 8, "E-mail", self.data["tomador_email"])
        
        self.draw_box(10, 93, 190, 8, "Nome / Nome Empresarial (Razão Social)", self.data["tomador_nome"], is_bold=True)
        
        tomador_cidade_uf = f"{self.data['tomador_municipio']} - {self.data['tomador_uf']}" if self.data['tomador_municipio'] != "-" else "-"
        self.draw_box(10, 101, 115, 8, "Endereço", self.data["tomador_endereco"])
        self.draw_box(125, 101, 45, 8, "Município", tomador_cidade_uf)
        self.draw_box(170, 101, 30, 8, "CEP", self.data["tomador_cep"])
        
        # --- Section: Intermediário ---
        self.draw_section_header(10, 110, 190, 4, "INTERMEDIÁRIO DO SERVIÇO")
        self.draw_box(10, 114, 190, 6, "Identificação do Intermediário do Serviço", "NÃO IDENTIFICADO NA NFS-e", "L")
        
        # --- Section: Serviço Prestado ---
        self.draw_section_header(10, 121, 190, 4, "SERVIÇO PRESTADO")
        self.draw_box(10, 125, 95, 8, "Código de Tributação Nacional", self.data["servico_codigo_nacional"])
        self.draw_box(105, 125, 95, 8, "Código de Tributação Municipal", self.data["servico_codigo_municipal"])
        
        servico_local_str = f"{self.data['servico_local']} - {self.data['tomador_uf']}" if self.data['servico_local'] != "-" else "-"
        self.draw_box(10, 133, 95, 8, "Local da Prestação do Serviço", servico_local_str)
        self.draw_box(105, 133, 95, 8, "País da Prestação do Serviço", self.data["servico_pais"])
        
        self.draw_multiline_box(10, 141, 190, 30, "Descrição / Discriminação do Serviço", self.data["servico_descricao"])
        
        # --- Section: Tributação Municipal ---
        self.draw_section_header(10, 172, 190, 4, "TRIBUTAÇÃO DO ISSQN E TAXAS MUNICIPAIS")
        self.draw_box(10, 176, 38, 8, "Valor do Serviço", self.data["valor_servico"], "R", True)
        self.draw_box(48, 176, 38, 8, "Desconto Incondicionado", self.data["desconto_incondicionado"], "R")
        self.draw_box(86, 176, 38, 8, "Total Deduções / Reduções", self.data["deducoes"], "R")
        self.draw_box(124, 176, 38, 8, "Base de Cálculo ISSQN", self.data["bc_issqn"], "R")
        self.draw_box(162, 176, 38, 8, "Alíquota Aplicada", self.data["aliq_iss"], "R")
        
        self.draw_box(10, 184, 47, 8, "Retenção do ISSQN", self.data["retencao_iss"])
        self.draw_box(57, 184, 48, 8, "ISSQN Apurado", self.data["iss_apurado"], "R")
        self.draw_box(105, 184, 47, 8, "ISSQN Retido", self.data["iss_retido"], "R")
        self.draw_box(152, 184, 48, 8, "Regime Especial de Tributação", self.data["regime_especial"])
        
        # --- Section: Tributação Federal ---
        self.draw_section_header(10, 193, 190, 4, "TRIBUTAÇÃO FEDERAL / RETENÇÕES")
        self.draw_box(10, 197, 38, 8, "PIS (Retido)", self.data["pis"], "R")
        self.draw_box(48, 197, 38, 8, "COFINS (Retido)", self.data["cofins"], "R")
        self.draw_box(86, 197, 38, 8, "CSLL (Retido)", self.data["csll"], "R")
        self.draw_box(124, 197, 38, 8, "IRRF (Retido)", self.data["irrf"], "R")
        self.draw_box(162, 197, 38, 8, "INSS (Retido)", self.data["inss"], "R")
        
        # --- Section: Totais ---
        self.draw_section_header(10, 206, 190, 4, "VALOR TOTAL DA NFS-e")
        self.draw_box(10, 210, 63, 10, "Valor do Serviço", self.data["valor_servico"], "C", True)
        self.draw_box(73, 210, 63, 10, "Total das Retenções Federais", self.data["retencoes_federais"], "C")
        self.draw_box(136, 210, 64, 10, "Valor Líquido da NFS-e", self.data["valor_liquido"], "C", True, title_color=(20, 40, 120))
        
        # --- Section: Informações Complementares ---
        self.draw_section_header(10, 221, 190, 4, "INFORMAÇÕES COMPLEMENTARES")
        self.draw_multiline_box(10, 225, 190, 36, "Observações / Detalhes de Apuração", self.data["informacoes_complementares"])

def generate_pdf_from_xml(xml_path, pdf_path):
    try:
        data = parse_xml_for_pdf(xml_path)
        pdf = DANFSePDF(data)
        pdf.build_invoice()
        pdf.output(pdf_path)
        return True, ""
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        return False, f"Exception: {str(e)}\n{err_msg}"
