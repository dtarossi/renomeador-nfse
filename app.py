import os
import re
import json
import subprocess
try:
    import requests
except ImportError:
    requests = None
import urllib.request
import urllib.error
import streamlit as st
import pdfplumber
import pandas as pd
import xml.etree.ElementTree as ET
import pdf_generator


# Set page configuration with a premium icon and theme
if st.runtime.exists():
    st.set_page_config(
        page_title="Renomeador Inteligente de Notas Fiscais",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

# File paths in workspace
MAPPINGS_FILE = "/Users/Tarossi/Library/CloudStorage/OneDrive-BibliotecasCompartilhadas-SELECTOCUPACIONALLTDA(2)/Communication site - Documentos/IA/SELECT/FISCAL/name_mappings.json"
CNPJ_DB_FILE = "/Users/Tarossi/Library/CloudStorage/OneDrive-BibliotecasCompartilhadas-SELECTOCUPACIONALLTDA(2)/Communication site - Documentos/IA/SELECT/FISCAL/cnpj_database.json"
SWIFT_OCR_SCRIPT = "/Users/Tarossi/.gemini/antigravity/scratch/ocr_pdf.swift"

# Helper to load/save manual name mappings (backward compatibility)
def load_mappings():
    if os.path.exists(MAPPINGS_FILE):
        try:
            with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_mappings(mappings):
    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False

# Helper to load/save CNPJ database
def load_cnpj_db():
    default_db = {"cnpjs": {}, "choices": {}}
    if os.path.exists(CNPJ_DB_FILE):
        try:
            with open(CNPJ_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "cnpjs" not in data:
                    data["cnpjs"] = {}
                if "choices" not in data:
                    data["choices"] = {}
                return data
        except Exception:
            return default_db
    return default_db

def save_cnpj_db(db):
    try:
        with open(CNPJ_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False

# Helper function to trigger native macOS folder dialog using AppleScript
def choose_folder():
    try:
        cmd = "osascript -e 'POSIX path of (choose folder with prompt \"Selecione a Pasta de Notas Fiscais\")'"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception as e:
        st.error(f"Erro ao abrir seletor nativo: {e}")
    return None

# Fetch CNPJ details from BrasilAPI
def fetch_cnpj_details(cnpj_digits):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_digits}"
    try:
        if requests is not None:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                res = response.json()
                return {
                    "razao_social": (res.get("razao_social") or "").strip(),
                    "nome_fantasia": (res.get("nome_fantasia") or "").strip()
                }
        else:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode("utf-8"))
                    return {
                        "razao_social": (res.get("razao_social") or "").strip(),
                        "nome_fantasia": (res.get("nome_fantasia") or "").strip()
                    }
    except Exception:
        pass
    return None

def format_cnpj_mask(val):
    if not val:
        return ""
    digits = re.sub(r'\D', '', str(val))
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    elif len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return str(val)

# Swift OCR Execution Function
def run_swift_ocr(pdf_path):
    if not os.path.exists(SWIFT_OCR_SCRIPT):
        return ""
    try:
        result = subprocess.run(
            ["swift", SWIFT_OCR_SCRIPT, pdf_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30
        )
        return result.stdout
    except Exception:
        return ""

def find_elem_insensitive(parent, tag_name):
    target = tag_name.lower()
    for elem in parent.iter():
        clean_tag = elem.tag.split('}', 1)[1] if '}' in elem.tag else elem.tag
        if clean_tag.lower() == target:
            return elem
    return None

# XML Namespace-insensitive parsing logic
def parse_xml_file(filepath):
    print(f"[debug] parse_xml_file called with filepath={filepath}")
    data = {
        "month": None,
        "prestador": None,
        "number": None,
        "cnpj": None,
        "tomador": None,
        "tomador_cnpj": None
    }
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # Parse XML directly
        root = ET.fromstring(content)
        print(f"[debug] XML parsed successfully. root.tag={root.tag}")
        
        # 1. NFS Number (NFS-e specific tags only: Numero, NumeroNfse, numero_nf, nNFS, NumeroNFS, numero_nfse)
        for tag in ['Numero', 'NumeroNfse', 'numero_nf', 'nNFS', 'NumeroNFS', 'numero_nfse']:
            elem = find_elem_insensitive(root, tag)
            if elem is not None and elem.text:
                val = elem.text.strip()
                print(f"[debug] Number tag found: {tag}={val}")
                if val.isdigit():
                    data["number"] = str(int(val))
                    break
        
        # 2. Date / Month of emission (NFS-e tags only: DataEmissao, data_emissao, dtEmissao)
        month_val = None
        for tag in ['DataEmissao', 'data_emissao', 'dtEmissao']:
            elem = find_elem_insensitive(root, tag)
            if elem is not None and elem.text:
                val = elem.text.strip()
                print(f"[debug] Month tag found: {tag}={val}")
                date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', val)
                if date_match:
                    month_val = date_match.group(2)
                    break
                else:
                    date_match2 = re.search(r'(\d{2})/(\d{2})/(\d{4})', val)
                    if date_match2:
                        month_val = date_match2.group(2)
                        break
        if month_val:
            data["month"] = month_val
            
        # Helper to search candidate tags in a container
        def get_child_text(container, tags):
            for t in tags:
                elem = find_elem_insensitive(container, t)
                if elem is not None and elem.text:
                    return elem.text.strip()
            return None

        # 3. Prestador (Emitente)
        # Check nested structures first
        prestador_elem = None
        for p_tag in ['Prestador', 'PrestadorServico', 'IdentificacaoPrestador']:
            prestador_elem = find_elem_insensitive(root, p_tag)
            if prestador_elem is not None:
                print(f"[debug] Prestador element found: tag={prestador_elem.tag}")
                break
                
        if prestador_elem is not None:
            cnpj_val = get_child_text(prestador_elem, ["CNPJ", "Cnpj", "CPF", "Cpf"])
            if cnpj_val:
                data["cnpj"] = re.sub(r'\D', '', cnpj_val)
                print(f"[debug] cnpj set to: {data['cnpj']}")
            name_val = get_child_text(prestador_elem, ["RazaoSocial", "Nome"])
            if name_val:
                data["prestador"] = name_val
        
        # Flat/Direct lookup fallback for Prestador
        if not data["cnpj"]:
            cnpj_val = get_child_text(root, ["cnpj_cpf_prestador", "cnpj_prestador", "cpf_prestador", "cnpj_cpf_emitente", "cnpj_emitente"])
            if cnpj_val:
                data["cnpj"] = re.sub(r'\D', '', cnpj_val)
                print(f"[debug] cnpj flat set to: {data['cnpj']}")
        if not data["prestador"]:
            name_val = get_child_text(root, ["razao_social_prestador", "razaosocial_prestador", "nome_prestador", "nome_fantasia_prestador", "razao_social_emitente", "nome_emitente"])
            if name_val:
                data["prestador"] = name_val
                
        # 4. Tomador (Destinatário)
        # Check nested structures first
        tomador_elem = None
        for t_tag in ['Tomador', 'TomadorServico', 'IdentificacaoTomador']:
            tomador_elem = find_elem_insensitive(root, t_tag)
            if tomador_elem is not None:
                print(f"[debug] Tomador element found: tag={tomador_elem.tag}")
                break
                
        if tomador_elem is not None:
            cnpj_val = get_child_text(tomador_elem, ["CNPJ", "Cnpj", "CPF", "Cpf"])
            if cnpj_val:
                data["tomador_cnpj"] = re.sub(r'\D', '', cnpj_val)
                print(f"[debug] tomador_cnpj set to: {data['tomador_cnpj']}")
            name_val = get_child_text(tomador_elem, ["RazaoSocial", "Nome"])
            if name_val:
                data["tomador"] = name_val
        
        # Flat/Direct lookup fallback for Tomador
        if not data["tomador_cnpj"]:
            cnpj_val = get_child_text(root, ["cnpj_cpf_destinatario", "cnpj_destinatario", "cnpj_cpf_tomador", "cnpj_tomador", "cpf_tomador"])
            if cnpj_val:
                data["tomador_cnpj"] = re.sub(r'\D', '', cnpj_val)
                print(f"[debug] tomador_cnpj flat set to: {data['tomador_cnpj']}")
        if not data["tomador"]:
            name_val = get_child_text(root, ["razao_social_destinatario", "razaosocial_destinatario", "nome_destinatario", "razao_social_tomador", "razaosocial_tomador", "nome_tomador"])
            if name_val:
                data["tomador"] = name_val
                
    except Exception as e:
        print(f"[debug] Exception raised: {e}")
        pass
        
    return data

# Robust space-insensitive and scanned-tolerant parsing logic
def parse_nfs_text(text):
    data = {
        "month": None,
        "prestador": None,
        "number": None,
        "cnpj": None,
        "tomador": None,
        "tomador_cnpj": None
    }
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return data
    
    # 0. CNPJ Extraction
    cnpj_match = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', text)
    if cnpj_match:
        # Check if it appears in the Prestador/Emitente area
        prestador_match_area = re.search(
            r'(?:PRESTADOR|EMITENTE)\s*(?:DE|DO|DA)?\s*(?:SERVIÇOS?|NFS-e|DADOS)(.*?)(?:TOMADOR|TOMADORDOSERVIÇO)', 
            text, 
            re.DOTALL | re.IGNORECASE
        )
        if prestador_match_area:
            area_text = prestador_match_area.group(1)
            area_cnpj = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', area_text)
            if area_cnpj:
                data["cnpj"] = re.sub(r'\D', '', area_cnpj.group(0))
        
        if not data["cnpj"]:
            data["cnpj"] = re.sub(r'\D', '', cnpj_match.group(0))
    
    # 1. PRESTADOR DE SERVIÇOS Extraction
    prestador_match = re.search(
        r'(?:PRESTADOR|EMITENTE)\s*(?:DE|DO|DA)?\s*(?:SERVIÇOS?|NFS-e|DADOS)(.*?)(?:TOMADOR|TOMADORDOSERVIÇO)', 
        text, 
        re.DOTALL | re.IGNORECASE
    )
    if prestador_match:
        prestador_section = prestador_match.group(1)
        section_lines = [l.strip() for l in prestador_section.split('\n') if l.strip()]
        
        for i, l in enumerate(section_lines):
            if re.search(r'(?:Nome\s*/\s*)?(?:Nome\s*Empresarial|Razão\s*Social)', l, re.IGNORECASE):
                if ":" in l:
                    data["prestador"] = l.split(":", 1)[1].strip()
                    break
                else:
                    if i + 1 < len(section_lines):
                        next_line = section_lines[i+1].strip()
                        next_line = re.sub(r'\S+@\S+', '', next_line).strip()
                        if next_line.upper() == "NOME FANTASIA" and i + 2 < len(section_lines):
                            next_line = section_lines[i+2].strip()
                        data["prestador"] = next_line
                        break
                        
        # Fallback 1: CNPJ-based extraction inside the prestador section
        if not data["prestador"] and data["cnpj"]:
            for i, l in enumerate(section_lines):
                if re.sub(r'\D', '', l) == data["cnpj"] or (len(data["cnpj"]) == 14 and data["cnpj"][:8] in re.sub(r'\D', '', l)):
                    if i + 1 < len(section_lines):
                        next_line = section_lines[i+1].strip()
                        next_line = re.sub(r'\S+@\S+', '', next_line).strip()
                        if not any(word in next_line.upper() for word in ["ENDEREÇO", "CNPJ", "TOMADOR", "TELEFONE", "MUNICÍPIO", "EMAIL", "PRESTADOR", "EMITENTE"]):
                            data["prestador"] = next_line
                            break
                                
    # Fallback 2: General match in the whole text
    if not data["prestador"]:
        for i, l in enumerate(lines):
            if re.search(r'(?:Nome\s*/\s*)?(?:Nome\s*Empresarial|Razão\s*Social)', l, re.IGNORECASE):
                if ":" in l:
                    data["prestador"] = l.split(":", 1)[1].strip()
                    break
                else:
                    if i + 1 < len(lines):
                        next_line = lines[i+1].strip()
                        next_line = re.sub(r'\S+@\S+', '', next_line).strip()
                        data["prestador"] = next_line
                        break

    # Clean Prestador name
    if data["prestador"]:
        data["prestador"] = re.sub(r'[\/*?:"<>|]', '', data["prestador"])
        data["prestador"] = data["prestador"].strip()

    # 2. MONTH OF EMISSION Extraction
    for idx, line in enumerate(lines):
        if re.search(r'data\s*e?\s*hora\s*(?:da|de)?\s*emiss[aã]o', line, re.IGNORECASE):
            for offset in [0, 1, 2]:
                if idx + offset < len(lines):
                    date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', lines[idx+offset])
                    if date_match:
                        data["month"] = date_match.group(2)
                        break
            if data["month"]:
                break
                
    if not data["month"]:
        date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
        if date_match:
            data["month"] = date_match.group(2)

    # 3. NFS NUMBER Extraction
    for idx, line in enumerate(lines):
        if re.search(r'n[uú]mero\s*(?:da)?\s*(?:nfs-e|nota)', line, re.IGNORECASE):
            found = False
            for offset in [1, 2, 3]:
                if idx + offset < len(lines):
                    parts = lines[idx+offset].split()
                    if parts:
                        cleaned = parts[0].replace(".", "").replace("-", "").strip()
                        if cleaned.isdigit():
                            data["number"] = str(int(cleaned))
                            found = True
                            break
            if found:
                break
                
    # Advanced Fallback 1: Extract from Chave de Acesso (performed line-by-line)
    if not data["number"]:
        typo_map = {'O': '0', 'Q': '0', 'U': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'G': '6', 'B': '8'}
        for line in lines:
            cleaned = re.sub(r'[^0-9a-zA-Z]', '', line)
            norm_line = "".join(typo_map.get(c.upper(), c) for c in cleaned if c.isdigit() or c.upper() in typo_map)
            
            # Check if this line looks like a Chave de Acesso (40 to 52 characters long)
            if 40 <= len(norm_line) <= 52:
                chave_match = re.search(r'(\d{9})[1-3]\d{13,14}$', norm_line)
                if chave_match:
                    data["number"] = str(int(chave_match.group(1)))
                    break
            
    # Fallback 2: General match
    if not data["number"]:
        match = re.search(r'Nota\s*Fiscal\s*(?:Eletrônica)?\s*(?:Nº|No|Number)?\s*(\d+)', text, re.IGNORECASE)
        if match:
            data["number"] = str(int(match.group(1)))
            
    # 4. TOMADOR DE SERVIÇOS Extraction
    tomador_match = re.search(
        r'(?:TOMADOR\s*(?:DE|DO|DA|DOS)?\s*SERVIÇOS?|DADOS\s*DO\s*TOMADOR|TOMADOR)(.*?)(?:INTERMEDIÁRIO|DESCRIÇÃO|CÓDIGO|VALOR|SERVIÇO|RETENÇÕES|DADOS|EXIGIBILIDADE|TRIBUTAÇÃO|FORMA|$)', 
        text, 
        re.DOTALL | re.IGNORECASE
    )
    if tomador_match:
        tomador_section = tomador_match.group(1)
        t_section_lines = [l.strip() for l in tomador_section.split('\n') if l.strip()]
        
        # Extract Tomador CNPJ inside section
        t_cnpj_match = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', tomador_section)
        if t_cnpj_match:
            data["tomador_cnpj"] = re.sub(r'\D', '', t_cnpj_match.group(0))
            
        # Extract Tomador Name inside section
        for i, l in enumerate(t_section_lines):
            if re.search(r'(?:Nome\s*/\s*)?(?:Nome\s*Empresarial|Razão\s*Social)', l, re.IGNORECASE):
                if ":" in l:
                    data["tomador"] = l.split(":", 1)[1].strip()
                    break
                else:
                    if i + 1 < len(t_section_lines):
                        next_line = t_section_lines[i+1].strip()
                        next_line = re.sub(r'\S+@\S+', '', next_line).strip()
                        if next_line.upper() == "NOME FANTASIA" and i + 2 < len(t_section_lines):
                            next_line = t_section_lines[i+2].strip()
                        data["tomador"] = next_line
                        break
                        
        # CNPJ-based fallback inside tomador section
        if not data["tomador"] and data["tomador_cnpj"]:
            for i, l in enumerate(t_section_lines):
                if re.sub(r'\D', '', l) == data["tomador_cnpj"] or (len(data["tomador_cnpj"]) == 14 and data["tomador_cnpj"][:8] in re.sub(r'\D', '', l)):
                    if i + 1 < len(t_section_lines):
                        next_line = t_section_lines[i+1].strip()
                        next_line = re.sub(r'\S+@\S+', '', next_line).strip()
                        if not any(word in next_line.upper() for word in ["ENDEREÇO", "CNPJ", "CPF", "INSCRIÇÃO", "TELEFONE", "MUNICÍPIO", "EMAIL", "PRESTADOR", "EMITENTE", "TOMADOR"]):
                            data["tomador"] = next_line
                            break
                            
    # Fallback for Tomador's CNPJ if not found in section:
    if not data.get("tomador_cnpj"):
        all_cnpjs = [re.sub(r'\D', '', match) for match in re.findall(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', text)]
        if len(all_cnpjs) >= 2:
            data["tomador_cnpj"] = all_cnpjs[1]
            
    # Clean Tomador name
    if data["tomador"]:
        data["tomador"] = re.sub(r'[\/*?:"<>|]', '', data["tomador"])
        data["tomador"] = data["tomador"].strip()
            
    return data

# Main logic execution
def process_folder(folder_path, naming_pattern, file_filter="Todos (PDF e XML)"):
    if not os.path.exists(folder_path):
        return []
        
    allowed_exts = []
    if file_filter == "Todos (PDF e XML)":
        allowed_exts = [".pdf", ".xml"]
    elif file_filter == "Apenas PDF":
        allowed_exts = [".pdf"]
    elif file_filter == "Apenas XML":
        allowed_exts = [".xml"]
    else:
        allowed_exts = [".pdf", ".xml"]
        
    all_files = [f for f in os.listdir(folder_path) if os.path.splitext(f)[1].lower() in allowed_exts]
    results = []
    
    mappings = st.session_state.mappings
    cnpj_db = st.session_state.cnpj_db
    manual_overrides = st.session_state.manual_overrides
    
    db_changed = False
    is_saida = "Saída" in naming_pattern
    
    for filename in all_files:
        filepath = os.path.join(folder_path, filename)
        ext = os.path.splitext(filename)[1].lower()
        
        if is_saida:
            is_already_renamed = bool(re.match(rf'^\d{{2}}\s*-\s*NFS\s*\d+\s*-\s*.*\{ext}$', filename, re.IGNORECASE))
        else:
            is_already_renamed = bool(re.match(rf'^\d{{2}}\s*-\s*.*\s*-\s*NFS\s*\d+\{ext}$', filename, re.IGNORECASE))
        
        try:
            if ext == ".xml":
                parsed = parse_xml_file(filepath)
                method = "XML"
            else:
                # 1. Try digital extraction first
                text = ""
                with pdfplumber.open(filepath) as pdf:
                    for page in pdf.pages:
                        text += page.extract_text() or ""
                
                method = "Digital"
                
                # 2. Fallback to OCR if digital text is empty or has CID font encoding errors
                if len(text.strip()) < 50 or "(cid:" in text:
                    text = run_swift_ocr(filepath)
                    method = "OCR"
                    
                parsed = parse_nfs_text(text)
            
            # Merge manual overrides
            overrides = manual_overrides.get(filename, {})
            
            if is_saida:
                cnpj = overrides.get("cnpj", parsed.get("tomador_cnpj"))
                original_prestador = parsed.get("tomador")
            else:
                cnpj = overrides.get("cnpj", parsed.get("cnpj"))
                original_prestador = parsed.get("prestador")
                
            month = overrides.get("month", parsed.get("month"))
            if month and str(month).isdigit():
                month = str(month).zfill(2)
            number = overrides.get("number", parsed.get("number"))
            resolved_name = overrides.get("prestador", original_prestador)
            
            # Resolving name using CNPJ preference system (Priority 1)
            if cnpj:
                # Check if CNPJ is cached in database
                if cnpj not in cnpj_db["cnpjs"]:
                    # Fetch from API
                    details = fetch_cnpj_details(cnpj)
                    if details:
                        cnpj_db["cnpjs"][cnpj] = details
                        # Set default choice to nome_fantasia if present, otherwise razao_social
                        cnpj_db["choices"][cnpj] = "nome_fantasia" if details["nome_fantasia"] else "razao_social"
                        db_changed = True
                    else:
                        # Fallback cache in case of API failure (uses parsed or manual name)
                        cnpj_db["cnpjs"][cnpj] = {
                            "razao_social": resolved_name if resolved_name else f"CNPJ {cnpj}",
                            "nome_fantasia": ""
                        }
                        cnpj_db["choices"][cnpj] = "razao_social"
                        db_changed = True
                
                # Fetch choice
                choice = cnpj_db["choices"].get(cnpj, "razao_social")
                details = cnpj_db["cnpjs"][cnpj]
                
                if choice == "nome_fantasia":
                    resolved_name = details["nome_fantasia"] if details["nome_fantasia"] else details["razao_social"]
                elif choice == "razao_social":
                    resolved_name = details["razao_social"]
                else:
                    # Custom user override choice
                    resolved_name = choice
            
            # Resolving name using manual mappings for backwards compatibility (Priority 2)
            if (not cnpj or not resolved_name) and original_prestador:
                norm_original = re.sub(r'\s+', '', original_prestador).upper()
                if original_prestador in mappings:
                    resolved_name = mappings[original_prestador]
                else:
                    for key, val in mappings.items():
                        if re.sub(r'\s+', '', key).upper() == norm_original:
                            resolved_name = val
                            break
            
            # Sanitization of resolved name
            if resolved_name:
                resolved_name = re.sub(r'[\/*?:"<>|]', '', resolved_name).strip()
            
            # Determine status and target name
            if month and resolved_name and number:
                if is_saida:
                    target_name = f"{month} - NFS {number} - {resolved_name}{ext}"
                else:
                    target_name = f"{month} - {resolved_name} - NFS {number}{ext}"
                if is_already_renamed and filename == target_name:
                    status = "already_renamed"
                else:
                    status = "ready"
            else:
                target_name = None
                status = "error"
                
            results.append({
                "filename": filename,
                "method": method,
                "cnpj": cnpj,
                "month": month,
                "prestador": original_prestador,
                "mapped_prestador": resolved_name,
                "number": number,
                "target_name": target_name,
                "status": status,
                "error_details": f"Falta: {'Mês ' if not month else ''}{'Prestador/CNPJ ' if not resolved_name else ''}{'Número NFS' if not number else ''}" if status == "error" else ""
            })
            
        except Exception as e:
            # Fallback block to rescue crashed extraction using manual overrides if present
            overrides = manual_overrides.get(filename, {})
            cnpj = overrides.get("cnpj", None)
            month = overrides.get("month", None)
            number = overrides.get("number", None)
            resolved_name = overrides.get("prestador", None)
            
            if month and resolved_name and number:
                if is_saida:
                    target_name = f"{month} - NFS {number} - {resolved_name}{ext}"
                else:
                    target_name = f"{month} - {resolved_name} - NFS {number}{ext}"
                status = "ready"
                error_details = ""
            else:
                target_name = None
                status = "error"
                error_details = f"Erro de Processamento: {str(e)}"
                
            results.append({
                "filename": filename,
                "method": "Erro",
                "cnpj": cnpj,
                "month": month,
                "prestador": None,
                "mapped_prestador": resolved_name,
                "number": number,
                "target_name": target_name,
                "status": status,
                "error_details": error_details
            })
            
    if db_changed:
        save_cnpj_db(cnpj_db)
        
    return results

if st.runtime.exists():
    # Initialize session state variables
    if "mappings" not in st.session_state:
        st.session_state.mappings = load_mappings()

    if "cnpj_db" not in st.session_state:
        st.session_state.cnpj_db = load_cnpj_db()

    if "manual_overrides" not in st.session_state:
        st.session_state.manual_overrides = {}

    if "naming_pattern" not in st.session_state:
        st.session_state.naming_pattern = "Notas de Entrada (Mês - Prestador - NFS Número)"

    if "active_directory" not in st.session_state:
        st.session_state.active_directory = "/Users/Tarossi/Library/CloudStorage/OneDrive-BibliotecasCompartilhadas-SELECTOCUPACIONALLTDA(2)/Communication site - Documentos/IA/SELECT/FISCAL"

    # Premium Visual CSS Styling (Glassmorphism & HSL gradients & Grid Glows)
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

        * {
            font-family: 'Outfit', sans-serif;
        }

        /* Main container background gradient */
        .stApp {
            background: linear-gradient(135deg, #090d16 0%, #0f172a 50%, #1e1b4b 100%);
            color: #f8fafc;
        }

        /* Hide Streamlit sidebar arrow and disable sidebar */
        [data-testid="collapsedControl"] {
            display: none;
        }

        /* Title and header styling */
        .main-header {
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 24px;
            padding: 2.2rem 2rem;
            margin-bottom: 1.8rem;
            box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.4);
            text-align: center;
            background-image: radial-gradient(at 0% 0%, hsla(253,16%,9%,1) 0, transparent 60%), 
                              radial-gradient(at 100% 0%, hsla(263,45%,25%,0.15) 0, transparent 60%);
            position: relative;
            overflow: hidden;
        }

        .main-header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 25%;
            width: 50%;
            height: 2px;
            background: linear-gradient(to right, transparent, #6366f1, #a855f7, #6366f1, transparent);
        }

        .main-header h1 {
            font-size: 2.8rem;
            font-weight: 700;
            background: linear-gradient(to right, #38bdf8, #818cf8, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.4rem;
            letter-spacing: -0.02em;
        }

        .main-header p {
            font-size: 1.1rem;
            color: #94a3b8;
            font-weight: 300;
            margin-bottom: 0;
            letter-spacing: 0.02em;
        }

        /* Elegant glassmorphic cards */
        .glass-card {
            background: rgba(15, 23, 42, 0.45);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 18px;
            padding: 1.8rem;
            margin-bottom: 1.8rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        }

        /* Status Badges */
        .status-badge {
            display: inline-block;
            padding: 0.1rem 0.3rem;
            border-radius: 9999px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            text-align: center;
            width: 100%;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .status-ready {
            background: rgba(16, 185, 129, 0.1);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.2);
        }
        .status-already {
            background: rgba(59, 130, 246, 0.1);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.2);
        }
        .status-error {
            background: rgba(244, 63, 94, 0.1);
            color: #fb7185;
            border: 1px solid rgba(244, 63, 94, 0.2);
        }

        /* Method Badges */
        .method-badge {
            display: inline-block;
            padding: 0.1rem 0.3rem;
            border-radius: 4px;
            font-size: 0.65rem;
            font-weight: 500;
            width: 100%;
            text-align: center;
        }
        .method-digital {
            background: rgba(255, 255, 255, 0.05);
            color: #cbd5e1;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .method-ocr {
            background: rgba(245, 158, 11, 0.1);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.2);
        }

        /* Button micro-animations */
        .stButton>button {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 0.55rem 1.6rem !important;
            font-weight: 600 !important;
            font-size: 0.9rem !important;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
            width: 100%;
        }
        .stButton>button:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 6px 18px rgba(99, 102, 241, 0.5) !important;
            background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
        }

        /* Custom Popover buttons in grid */
        .stPopover>button {
            background: rgba(99, 102, 241, 0.12) !important;
            color: #cbd5e1 !important;
            border: 1px solid rgba(99, 102, 241, 0.22) !important;
            border-radius: 4px !important;
            padding: 0.12rem 0.3rem !important;
            font-size: 0.7rem !important;
            font-weight: 500 !important;
            transition: all 0.2s ease !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            height: 23px !important;
            line-height: 1.2 !important;
        }
        .stPopover>button:hover {
            background: rgba(99, 102, 241, 0.25) !important;
            border-color: rgba(99, 102, 241, 0.5) !important;
            color: #ffffff !important;
        }

        /* Style the text inputs inside the preview table to be extremely compact and high-contrast */
        div[data-testid="stTextInput"] input {
            padding: 0.1rem 0.35rem !important;
            height: 23px !important;
            min-height: 23px !important;
            font-size: 0.74rem !important;
            font-weight: 600 !important;
            border-radius: 4px !important;
            background-color: #0f172a !important; /* Deep dark high-contrast background */
            color: #38bdf8 !important; /* Bright high-contrast Sky Blue text color */
            border: 1px solid rgba(99, 102, 241, 0.4) !important; /* Slate/indigo border */
            box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5) !important;
        }
        div[data-testid="stTextInput"] input:focus {
            border-color: #38bdf8 !important;
            box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2) !important;
            color: #ffffff !important;
        }
        div[data-testid="stTextInput"] {
            padding-top: 0px !important;
            padding-bottom: 0px !important;
            margin-top: 0px !important;
            margin-bottom: 0px !important;
        }

        /* Code style inside table columns */
        .compact-code {
            font-size: 0.72rem !important;
            padding: 1px 3px !important;
            background: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid rgba(255, 255, 255, 0.06) !important;
        }

        /* Premium Metric Cards */
        .premium-metric-container {
            display: flex;
            gap: 1.2rem;
            margin-bottom: 1.8rem;
            width: 100%;
        }

        .premium-metric-card {
            flex: 1;
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-radius: 14px;
            padding: 1.2rem;
            display: flex;
            align-items: center;
            gap: 1rem;
            box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        .premium-metric-card::after {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            height: 100%;
            width: 4px;
        }

        .metric-ready {
            border: 1px solid rgba(16, 185, 129, 0.12);
            background: radial-gradient(circle at 100% 100%, rgba(16, 185, 129, 0.02) 0%, transparent 60%);
        }
        .metric-ready::after {
            background: #10b981;
            box-shadow: 0 0 8px #10b981;
        }
        .metric-ready .metric-icon-box {
            background: rgba(16, 185, 129, 0.08);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.15);
        }

        .metric-already {
            border: 1px solid rgba(14, 165, 233, 0.12);
            background: radial-gradient(circle at 100% 100%, rgba(14, 165, 233, 0.02) 0%, transparent 60%);
        }
        .metric-already::after {
            background: #0ea5e9;
            box-shadow: 0 0 8px #0ea5e9;
        }
        .metric-already .metric-icon-box {
            background: rgba(14, 165, 233, 0.08);
            color: #38bdf8;
            border: 1px solid rgba(14, 165, 233, 0.15);
        }

        .metric-error {
            border: 1px solid rgba(244, 63, 94, 0.12);
            background: radial-gradient(circle at 100% 100%, rgba(244, 63, 94, 0.02) 0%, transparent 60%);
        }
        .metric-error::after {
            background: #f43f5e;
            box-shadow: 0 0 8px #f43f5e;
        }
        .metric-error .metric-icon-box {
            background: rgba(244, 63, 94, 0.08);
            color: #fb7185;
            border: 1px solid rgba(244, 63, 94, 0.15);
        }

        .metric-icon-box {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.3rem;
            font-weight: bold;
        }

        .metric-content {
            display: flex;
            flex-direction: column;
        }

        .metric-val {
            font-size: 1.8rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 0.1rem;
            color: #ffffff;
        }

        .metric-lbl {
            font-size: 0.8rem;
            color: #94a3b8;
            font-weight: 400;
            letter-spacing: 0.02em;
        }

        /* Styled code tag */
        code {
            color: #38bdf8 !important;
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-family: monospace !important;
            font-size: 0.88em !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Helper function to trigger native macOS folder dialog using AppleScript
    # HEADER CARD
    st.markdown("""
    <div class="main-header">
        <h1>Renomeador Inteligente de Notas Fiscais</h1>
    </div>
    """, unsafe_allow_html=True)

    # Detect if running locally on macOS with local directory support
    is_mac_local = os.path.exists("/Users/Tarossi") and sys.platform == "darwin"

    # TOP TOOLBAR: HYBRID FILE ORIGIN AND NAMING PATTERN SELECTOR
    st.markdown('<div class="glass-card" style="margin-bottom: 1.5rem; padding: 1.2rem;">', unsafe_allow_html=True)
    col_uploader, col_conversion, col_pattern, col_filter = st.columns([3.0, 1.5, 1.9, 1.6])

    with col_uploader:
        if is_mac_local:
            source_mode = st.radio(
                "📂 Origem dos Arquivos:",
                options=["📁 Pasta Local do Mac (Direto)", "📤 Upload de Arquivos"],
                horizontal=True,
                key="source_mode"
            )
            if source_mode == "📁 Pasta Local do Mac (Direto)":
                col_path_text, col_btn_pick = st.columns([2.0, 1.0])
                with col_path_text:
                    st.markdown(f"<div style='margin-top: 4px;'><small><b>Pasta Atual:</b><br><code style='font-size:0.85em;'>{st.session_state.active_directory}</code></small></div>", unsafe_allow_html=True)
                with col_btn_pick:
                    if st.button("📁 Selecionar Pasta", key="btn_choose_folder_mac"):
                        new_path = choose_folder()
                        if new_path:
                            st.session_state.active_directory = new_path
                            st.rerun()
            else:
                uploaded_files = st.file_uploader(
                    "📤 Upload de Arquivos (PDF e XML):",
                    type=["pdf", "xml"],
                    accept_multiple_files=True,
                    key="header_file_uploader"
                )
                if uploaded_files:
                    cloud_workdir = "/tmp/nfse_cloud_workdir"
                    os.makedirs(cloud_workdir, exist_ok=True)
                    for old_f in os.listdir(cloud_workdir):
                        try:
                            os.remove(os.path.join(cloud_workdir, old_f))
                        except Exception:
                            pass
                    for uf in uploaded_files:
                        target_path = os.path.join(cloud_workdir, uf.name)
                        with open(target_path, "wb") as f:
                            f.write(uf.getbuffer())
                    if st.session_state.active_directory != cloud_workdir:
                        st.session_state.active_directory = cloud_workdir
                        st.rerun()
        else:
            uploaded_files = st.file_uploader(
                "📤 Upload de Arquivos (PDF e XML):",
                type=["pdf", "xml"],
                accept_multiple_files=True,
                key="header_file_uploader"
            )
            if uploaded_files:
                cloud_workdir = "/tmp/nfse_cloud_workdir"
                os.makedirs(cloud_workdir, exist_ok=True)
                for old_f in os.listdir(cloud_workdir):
                    try:
                        os.remove(os.path.join(cloud_workdir, old_f))
                    except Exception:
                        pass
                for uf in uploaded_files:
                    target_path = os.path.join(cloud_workdir, uf.name)
                    with open(target_path, "wb") as f:
                        f.write(uf.getbuffer())
                if st.session_state.active_directory != cloud_workdir:
                    st.session_state.active_directory = cloud_workdir
                    st.rerun()

    with col_conversion:
        conversion_option = st.selectbox(
            "📄 Conversão de Layout:",
            options=["XML para PDF", "PDF para PDF", "Sem Conversão"],
            index=0,
            key="conversion_option"
        )

    with col_pattern:
        naming_pattern = st.selectbox(
            "📋 Padrão de Nomenclatura:",
            options=["Notas de Entrada (Mês - Prestador - NFS Número)", "Notas de Saída (Mês - NFS Número - Prestador)"],
            index=0,
            key="naming_pattern"
        )

    with col_filter:
        file_filter = st.selectbox(
            "🔍 Filtrar Arquivos:",
            options=["Todos (PDF e XML)", "Apenas PDF", "Apenas XML"],
            index=0,
            key="file_filter"
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # Validate directory access and process files
    active_directory = st.session_state.active_directory

    if not os.path.exists(active_directory) or not os.listdir(active_directory):
        st.info("💡 Por favor, envie seus arquivos PDF e XML no campo **Upload de Arquivos** acima para iniciar a análise e renomeação.")
        file_results = []
    else:
        # Automatic conversion trigger based on dropdown selection
        if st.session_state.get("conversion_option") == "XML para PDF":
            for f in os.listdir(active_directory):
                if f.lower().endswith(".xml"):
                    xml_path = os.path.join(active_directory, f)
                    pdf_name = os.path.splitext(f)[0] + ".pdf"
                    pdf_path = os.path.join(active_directory, pdf_name)
                    if not os.path.exists(pdf_path):
                        pdf_generator.generate_pdf_from_xml(xml_path, pdf_path)

        # Process files
        with st.spinner("Analisando arquivos PDF/XML..."):
            file_results = process_folder(active_directory, st.session_state.naming_pattern, st.session_state.file_filter)

        if not file_results:
            st.warning("⚠️ Nenhum arquivo PDF ou XML foi encontrado entre os arquivos enviados.")
        else:
            # 1. MONITORING PANEL (Top level metrics glows)
            ready_count = sum(1 for r in file_results if r["status"] == "ready")
            already_count = sum(1 for r in file_results if r["status"] == "already_renamed")
            error_count = sum(1 for r in file_results if r["status"] == "error")

            st.markdown(f"""
            <div class="premium-metric-container">
                <div class="premium-metric-card metric-ready">
                    <div class="metric-icon-box">✓</div>
                    <div class="metric-content">
                        <span class="metric-val">{ready_count}</span>
                        <span class="metric-lbl">Prontos para Renomear</span>
                    </div>
                </div>
                <div class="premium-metric-card metric-already">
                    <div class="metric-icon-box">✦</div>
                    <div class="metric-content">
                        <span class="metric-val">{already_count}</span>
                        <span class="metric-lbl">Já Padronizados</span>
                    </div>
                </div>
                <div class="premium-metric-card metric-error">
                    <div class="metric-icon-box">!</div>
                    <div class="metric-content">
                        <span class="metric-val">{error_count}</span>
                        <span class="metric-lbl">Erros de Extração</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 2. MAIN PREVIEW GRID CARD (Takes 100% width)
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("### Prévia de Renomeação em Lote")
            st.markdown("<small style='color:#94a3b8;'>Clique no CNPJ para ajustar a preferência de nomenclatura (Razão Social, Nome Fantasia ou Personalisar) de forma interativa por prestador.</small><br><br>", unsafe_allow_html=True)

            # Grid Columns Header Definition
            col_status, col_method, col_file, col_cnpj, col_month, col_prestador, col_nfs, col_target = st.columns([0.6, 0.7, 2.6, 1.2, 0.4, 3.2, 0.6, 3.5])

            col_status.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Status</small>", unsafe_allow_html=True)
            col_method.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Método</small>", unsafe_allow_html=True)
            col_file.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Nome Atual</small>", unsafe_allow_html=True)
            col_cnpj.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>CNPJ Prestador</small>", unsafe_allow_html=True)
            col_month.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Mês</small>", unsafe_allow_html=True)
            col_prestador.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Razão Social / Nome Utilizado</small>", unsafe_allow_html=True)
            col_nfs.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>NFS Nº</small>", unsafe_allow_html=True)
            col_target.markdown("<small style='color:#a5b4fc; font-weight:600; text-transform:uppercase; font-size:0.82rem;'>Novo Nome Proposto</small>", unsafe_allow_html=True)

            st.markdown("<hr style='margin: 0.5rem 0; border-color: rgba(255,255,255,0.12);'>", unsafe_allow_html=True)

            cnpj_db = st.session_state.cnpj_db
            db_changed = False

            # Grid Rows Rendering
            for idx, r in enumerate(file_results):
                # Outer grid columns wrapper
                col_status_c, col_method_c, col_file_c, col_cnpj_c, col_month_c, col_prestador_c, col_nfs_c, col_target_c = st.columns([0.6, 0.7, 2.6, 1.2, 0.4, 3.2, 0.6, 3.5])

                # Status Badge
                if r["status"] == "ready":
                    status_html = '<span class="status-badge status-ready">Pronto</span>'
                elif r["status"] == "already_renamed":
                    status_html = '<span class="status-badge status-already">Já Renomeado</span>'
                else:
                    status_html = '<span class="status-badge status-error">Erro</span>'
                col_status_c.markdown(f"<div style='margin-top: 2px;'>{status_html}</div>", unsafe_allow_html=True)

                # Method Badge
                if r["method"] == "Digital":
                    method_html = '<span class="method-badge method-digital">Digital</span>'
                    col_method_c.markdown(f"<div style='margin-top: 2px;'>{method_html}</div>", unsafe_allow_html=True)
                elif r["method"] == "OCR":
                    method_html = '<span class="method-badge method-ocr">OCR • Apple</span>'
                    col_method_c.markdown(f"<div style='margin-top: 2px;'>{method_html}</div>", unsafe_allow_html=True)
                elif r["method"] == "XML":
                    with col_method_c:
                        if st.button("📄 PDF", key=f"btn_gen_pdf_{r['filename']}_{idx}", help="Gerar visualização PDF deste XML"):
                            xml_path = os.path.join(active_directory, r["filename"])
                            pdf_name = os.path.splitext(r["filename"])[0] + ".pdf"
                            pdf_path = os.path.join(active_directory, pdf_name)
                            success, err = pdf_generator.generate_pdf_from_xml(xml_path, pdf_path)
                            if success:
                                st.toast(f"PDF gerado com sucesso para {r['filename']}! 🎉")
                                st.rerun()
                            else:
                                st.error(f"Erro ao gerar PDF: {err}")
                else:
                    method_html = '<span class="method-badge method-digital">-</span>'
                    col_method_c.markdown(f"<div style='margin-top: 2px;'>{method_html}</div>", unsafe_allow_html=True)

                # Original Filename
                col_file_c.markdown(f"<div style='margin-top: 3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:280px;' title='{r['filename']}'><small><code class='compact-code'>{r['filename']}</code></small></div>", unsafe_allow_html=True)

                # CNPJ Interactive Popover or Manual Input
                cnpj = r["cnpj"]
                if cnpj:
                    cnpj_mask = format_cnpj_mask(cnpj)

                    with col_cnpj_c:
                        # Interactive popover triggers native dialog in place
                        with st.popover(f"{cnpj_mask} 🔍", use_container_width=True):
                            st.markdown(f"**CNPJ/CPF:** `{cnpj_mask}`")

                            details = cnpj_db["cnpjs"].get(cnpj, {})
                            razao = details.get("razao_social", r["prestador"] if r["prestador"] else f"CNPJ {cnpj}")
                            fantasia = details.get("nome_fantasia", "")

                            st.markdown(f"<small>• <b>Razão:</b> {razao}</small>", unsafe_allow_html=True)
                            if fantasia:
                                st.markdown(f"<small>• <b>Fantasia:</b> {fantasia}</small>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<small>• <b>Fantasia:</b> <i>(Não cadastrado - usará Razão Social)</i></small>", unsafe_allow_html=True)

                            options = ["Razão Social", "Nome Fantasia", "Personalisar"]
                            options_map = {
                                "razao_social": "Razão Social",
                                "nome_fantasia": "Nome Fantasia"
                            }

                            current_choice = cnpj_db["choices"].get(cnpj, "razao_social")
                            is_custom = current_choice not in ["razao_social", "nome_fantasia"]

                            if is_custom:
                                options_map[current_choice] = "Personalisar"

                            selected_value_label = options_map.get(current_choice, "Razão Social")
                            try:
                                default_index = options.index(selected_value_label)
                            except ValueError:
                                default_index = 0

                            selected_label = st.radio(
                                "Padrão de Nome:",
                                options=options,
                                index=default_index,
                                key=f"radio_cnpj_{cnpj}_{idx}"
                            )

                            if selected_label == "Personalisar":
                                if not is_custom:
                                    # When selecting custom, initialize it with official Razão Social
                                    cnpj_db["choices"][cnpj] = razao
                                    db_changed = True
                            else:
                                mapped_choice = "razao_social" if selected_label == "Razão Social" else "nome_fantasia"
                                if mapped_choice != current_choice:
                                    cnpj_db["choices"][cnpj] = mapped_choice
                                    db_changed = True

                            # CNPJ Manual Override / Correction Text Input
                            st.markdown("---")
                            new_cnpj_input = st.text_input(
                                "Alterar CNPJ:",
                                value=cnpj,
                                key=f"edit_cnpj_{cnpj}_{idx}",
                                placeholder="Deixe em branco para limpar"
                            )
                            if new_cnpj_input != cnpj:
                                digits = re.sub(r'\D', '', new_cnpj_input)
                                if not digits:
                                    if r["filename"] not in st.session_state.manual_overrides:
                                        st.session_state.manual_overrides[r["filename"]] = {}
                                    st.session_state.manual_overrides[r["filename"]]["cnpj"] = ""
                                    st.rerun()
                                elif len(digits) == 14:
                                    if r["filename"] not in st.session_state.manual_overrides:
                                        st.session_state.manual_overrides[r["filename"]] = {}
                                    st.session_state.manual_overrides[r["filename"]]["cnpj"] = digits
                                    st.rerun()
                else:
                    # Missing CNPJ turns into an active compact text input
                    with col_cnpj_c:
                        cnpj_input = st.text_input(
                            "Digitar CNPJ",
                            value="",
                            key=f"input_manual_cnpj_{r['filename']}_{idx}",
                            label_visibility="collapsed",
                            placeholder="Digitar CNPJ"
                        )
                        if cnpj_input:
                            digits = re.sub(r'\D', '', cnpj_input)
                            if len(digits) == 14:
                                if r["filename"] not in st.session_state.manual_overrides:
                                    st.session_state.manual_overrides[r["filename"]] = {}
                                st.session_state.manual_overrides[r["filename"]]["cnpj"] = digits
                                st.rerun()

                # Month: Display or Manual Override Input
                with col_month_c:
                    if r["month"]:
                        st.markdown(f"<div style='margin-top: 2.5px; text-align:center; font-size:0.78rem; font-weight:600; color:#e2e8f0;'>{r['month']}</div>", unsafe_allow_html=True)
                    else:
                        month_input = st.text_input(
                            "MM",
                            value="",
                            key=f"input_manual_month_{r['filename']}_{idx}",
                            label_visibility="collapsed",
                            placeholder="MM"
                        )
                        if month_input:
                            if month_input.isdigit() and len(month_input) in [1, 2]:
                                formatted_month = month_input.zfill(2)
                                if r["filename"] not in st.session_state.manual_overrides:
                                    st.session_state.manual_overrides[r["filename"]] = {}
                                st.session_state.manual_overrides[r["filename"]]["month"] = formatted_month
                                st.rerun()

                # Razão Social / Nome Utilizado: static display vs inline input editor vs direct manual name input
                with col_prestador_c:
                    if cnpj:
                        current_choice = cnpj_db["choices"].get(cnpj, "razao_social")
                        is_custom = current_choice not in ["razao_social", "nome_fantasia"]

                        if is_custom:
                            # Inline Text Input Field enabled for Custom Names
                            custom_name = st.text_input(
                                f"Editar Nome {cnpj_mask}",
                                value=current_choice,
                                key=f"input_prestador_{cnpj}_{idx}",
                                label_visibility="collapsed"
                            )
                            if custom_name != current_choice:
                                cnpj_db["choices"][cnpj] = custom_name
                                db_changed = True
                        else:
                            prestador_display = r["prestador"]
                            if r["prestador"] != r["mapped_prestador"]:
                                prestador_display = f'<span style="color:#64748b; text-decoration:line-through; font-size:0.78em; font-weight:300;">{r["prestador"]}</span> ➔ <span class="highlight-text" style="color:#38bdf8; font-weight:600;">{r["mapped_prestador"]}</span>'
                            st.markdown(f"<div style='font-size:0.78rem; font-weight:500; margin-top:2.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:350px;' title='{r['mapped_prestador']}'>{prestador_display}</div>", unsafe_allow_html=True)
                    else:
                        # Allow manual name override for files without CNPJ
                        manual_name = st.text_input(
                            "Nome Prestador",
                            value=r["prestador"] if r["prestador"] else "",
                            key=f"input_manual_name_{r['filename']}_{idx}",
                            label_visibility="collapsed",
                            placeholder="Digitar Nome"
                        )
                        if manual_name and manual_name != r["prestador"]:
                            if r["filename"] not in st.session_state.manual_overrides:
                                st.session_state.manual_overrides[r["filename"]] = {}
                            st.session_state.manual_overrides[r["filename"]]["prestador"] = manual_name
                            st.rerun()

                # NFS Number: Display or Manual Override Input
                with col_nfs_c:
                    if r["number"]:
                        st.markdown(f"<div style='margin-top: 2.5px; text-align:center; font-size:0.78rem; font-weight:600; color:#e2e8f0;'>{r['number']}</div>", unsafe_allow_html=True)
                    else:
                        number_input = st.text_input(
                            "NFS",
                            value="",
                            key=f"input_manual_number_{r['filename']}_{idx}",
                            label_visibility="collapsed",
                            placeholder="Nota"
                        )
                        if number_input:
                            if number_input.strip():
                                if r["filename"] not in st.session_state.manual_overrides:
                                    st.session_state.manual_overrides[r["filename"]] = {}
                                st.session_state.manual_overrides[r["filename"]]["number"] = number_input.strip()
                                st.rerun()

                # Target Filename Proposed
                target_html = f"<div style='margin-top: 3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:380px;' title='{r['target_name']}'><code class='compact-code' style='color:#34d399;'>{r['target_name']}</code></div>" if r["target_name"] else f'<div style="margin-top: 3px; color:#f43f5e; font-weight:500; font-size:0.78rem;">{r["error_details"]}</div>'
                col_target_c.markdown(target_html, unsafe_allow_html=True)

                # Row Divider
                st.markdown("<hr style='margin: 0.15rem 0; border-color: rgba(255,255,255,0.04);'>", unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

            if db_changed:
                save_cnpj_db(cnpj_db)
                st.rerun()

            # 3. ACTION CENTER / EXECUTION CONSOLE (Bottom level container)
            st.markdown('<div class="glass-card" style="position: relative; overflow: hidden; background-image: radial-gradient(at 0% 100%, rgba(99, 102, 241, 0.06) 0, transparent 40%);">', unsafe_allow_html=True)
            st.markdown("### Centro de Execução")
            st.markdown("<small style='color:#94a3b8;'>Defina o modo operacional abaixo e clique no botão de disparo principal.</small><br><br>", unsafe_allow_html=True)

            col_mode_sel, col_exec_trigger = st.columns([3, 1])

            with col_mode_sel:
                execution_mode = st.radio(
                    "Modo de Operação:",
                    options=["Simulação (Dry Run) - Totalmente Seguro", "Renomear Arquivos de Fato"],
                    index=0,
                    horizontal=True
                )
                is_dry_run = "Simulação" in execution_mode

            with col_exec_trigger:
                st.markdown("<div style='margin-top: 15px;'>", unsafe_allow_html=True)
                btn_label = "Simular Renomeação" if is_dry_run else "Executar Renomeação"
                btn_clicked = st.button(btn_label, key="btn_run_execution")
                st.markdown("</div>", unsafe_allow_html=True)

            if btn_clicked:
                progress_bar = st.progress(0.0)
                status_text = st.empty()

                success_list = []
                failed_list = []

                for idx, r in enumerate(file_results):
                    current_progress = (idx + 1) / len(file_results)
                    progress_bar.progress(current_progress)

                    if r["status"] == "ready" and r["target_name"]:
                        old_path = os.path.join(active_directory, r["filename"])
                        new_path = os.path.join(active_directory, r["target_name"])

                        if is_dry_run:
                            success_list.append((r["filename"], r["target_name"]))
                        else:
                            try:
                                if os.path.exists(new_path) and r["filename"] != r["target_name"]:
                                    raise FileExistsError(f"O arquivo '{r['target_name']}' já existe.")

                                os.rename(old_path, new_path)
                                success_list.append((r["filename"], r["target_name"]))
                            except Exception as e:
                                failed_list.append((r["filename"], str(e)))
                    elif r["status"] == "already_renamed":
                        pass
                    elif r["status"] == "error":
                        failed_list.append((r["filename"], r["error_details"]))

                status_text.success("Processamento concluído com sucesso!")

                st.markdown("---")
                st.markdown("#### Relatório de Execução")

                if is_dry_run:
                    st.markdown(f"**Simulação realizada com sucesso!**")
                    st.markdown(f"- **Total de arquivos simulados com sucesso**: {len(success_list)}")
                    if success_list:
                        with st.expander("Ver arquivos simulados"):
                            for old, new in success_list:
                                st.markdown(f"• `{old}` ➔ `<span style='color:#34d399;'>{new}</span>`", unsafe_allow_html=True)
                else:
                    st.markdown(f"**Renomeação concluída!**")
                    st.markdown(f"- **Arquivos renomeados com sucesso**: {len(success_list)}")
                    st.markdown(f"- **Falhas**: {len(failed_list)}")

                    if success_list:
                        with st.expander("Ver arquivos renomeados com sucesso"):
                            for old, new in success_list:
                                st.markdown(f"• `{old}` ➔ `<span style='color:#34d399;'>{new}</span>`", unsafe_allow_html=True)

                    if failed_list:
                        with st.expander("Ver falhas / erros"):
                            for name, err in failed_list:
                                st.markdown(f"• `{name}`: <span style='color:#f87171;'>{err}</span>", unsafe_allow_html=True)

                if active_directory == "/tmp/nfse_cloud_workdir" or not os.path.exists("/Users/Tarossi"):
                    import io
                    import zipfile
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                        for f in os.listdir(active_directory):
                            fp = os.path.join(active_directory, f)
                            if os.path.isfile(fp):
                                zf.write(fp, arcname=f)
                    zip_buffer.seek(0)
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.download_button(
                        label="📦 Baixar Todos os Arquivos Renomeados (.ZIP)",
                        data=zip_buffer,
                        file_name="nfse_renomeadas.zip",
                        mime="application/zip",
                        key="btn_download_zip_report"
                    )

                st.button("Atualizar Painel / Recarregar")

            st.markdown('</div>', unsafe_allow_html=True)

            # 4. BACKWARD COMPATIBLE MANUAL DICTIONARY (Bottom drawer expander)
            with st.expander("📂 Gerenciar Mapeamentos Manuais (Notas sem CNPJ)"):
                st.markdown("<small style='color:#94a3b8;'>Utilize este dicionário apenas para Notas Fiscais que não possuam CNPJ extraído pelo leitor. Notas com CNPJ devem ser configuradas diretamente na tabela acima.</small>", unsafe_allow_html=True)

                # Add manual mapping form
                with st.form("add_mapping_form_bottom", clear_on_submit=True):
                    col_m1, col_m2, col_m3 = st.columns([2.5, 2.5, 1])
                    with col_m1:
                        input_official = st.text_input("Razão Social do Arquivo (bruta):")
                    with col_m2:
                        input_commercial = st.text_input("Nome Fantasia Desejado (para o arquivo):")
                    with col_m3:
                        st.markdown("<div style='margin-top:24px;'>", unsafe_allow_html=True)
                        submitted = st.form_submit_button("Salvar")
                        st.markdown("</div>", unsafe_allow_html=True)

                    if submitted and input_official and input_commercial:
                        st.session_state.mappings[input_official.strip()] = input_commercial.strip()
                        if save_mappings(st.session_state.mappings):
                            st.toast("Mapeamento manual salvo com sucesso! 🎉")
                            st.rerun()

                # List manual mappings
                if st.session_state.mappings:
                    st.markdown("**Mapeamentos Manuais Ativos:**")
                    for key, value in list(st.session_state.mappings.items()):
                        col_k, col_v, col_del = st.columns([3, 3, 1])
                        col_k.markdown(f"<small><code>{key}</code></small>", unsafe_allow_html=True)
                        col_v.markdown(f"<small>➔ <b>{value}</b></small>", unsafe_allow_html=True)
                        if col_del.button("🗑️ Deletar", key=f"del_map_{key}"):
                            del st.session_state.mappings[key]
                            save_mappings(st.session_state.mappings)
                            st.rerun()
