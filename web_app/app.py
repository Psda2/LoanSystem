import os
import requests
import re
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

# Fuseki Configuration
FUSEKI_BASE_URL = "http://localhost:3030/SWOE"
FUSEKI_QUERY_URL = f"{FUSEKI_BASE_URL}/query"
FUSEKI_UPDATE_URL = f"{FUSEKI_BASE_URL}/update"
FUSEKI_DATA_URL = f"{FUSEKI_BASE_URL}/data"

def perform_logical_assessment(applicant_data):
    """
    Simulates OWL reasoning by checking applicant data against ontology constraints.
    Returns (status, category/reason)
    """
    if not ONTOLOGY_CONSTRAINTS: load_ontology_constraints()
    
    # Check for Rejections first
    for rej_class, rules in ONTOLOGY_CONSTRAINTS.items():
        if "Rejection" not in rej_class and "Applicant" not in rej_class: continue
        if "Approved" in rej_class: continue
        
        matches_all = True
        for rule in rules:
            val = applicant_data.get(rule['prop'])
            if val is None:
                matches_all = False
                break
            op = rule['type']
            target = rule['val']
            try:
                if op == 'hasValue' and val != target: matches_all = False
                elif op == 'minInclusive' and float(val) < float(target): matches_all = False
                elif op == 'maxInclusive' and float(val) > float(target): matches_all = False
                elif op == 'maxExclusive' and float(val) >= float(target): matches_all = False
                elif op == 'minExclusive' and float(val) <= float(target): matches_all = False
            except (ValueError, TypeError):
                matches_all = False
            if not matches_all: break
            
        if matches_all:
            import re
            return "Rejected", re.sub(r'([A-Z])', r' \1', rej_class).strip()
            
    # Check for Approvals
    for app_class, rules in ONTOLOGY_CONSTRAINTS.items():
        if "Approved" not in app_class: continue
        
        matches_all = True
        for rule in rules:
            val = applicant_data.get(rule['prop'])
            if val is None:
                matches_all = False
                break
            op = rule['type']
            target = rule['val']
            try:
                if op == 'hasValue' and val != target: matches_all = False
                elif op == 'minInclusive' and float(val) < float(target): matches_all = False
                elif op == 'maxInclusive' and float(val) > float(target): matches_all = False
            except (ValueError, TypeError):
                matches_all = False
            if not matches_all: break
            
        if matches_all:
            import re
            return "Approved", re.sub(r'([A-Z])', r' \1', app_class).strip()
            
    return "Pending", "Awaiting Reasoning Outcome"

def query_fuseki(sparql_query):
    """Executes a SPARQL query against the Fuseki endpoint."""
    try:
        response = requests.post(
            FUSEKI_QUERY_URL,
            data={'query': sparql_query},
            headers={'Accept': 'application/sparql-results+json'}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Fuseki Query Error: {e}")
        return None

def update_fuseki(sparql_update):
    """Executes a SPARQL UPDATE against the Fuseki endpoint."""
    try:
        response = requests.post(
            FUSEKI_UPDATE_URL,
            data={'update': sparql_update}
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Fuseki Update Error: {e}")
        return False

def sync_ontology_to_fuseki():
    """Reads the local OWL file and pushes it to Fuseki."""
    ontology_path = os.path.join(os.path.dirname(__file__), "..", "loan_approval.owl")
    if not os.path.exists(ontology_path):
        return False, "Ontology file not found."
    
    try:
        with open(ontology_path, 'rb') as f:
            data = f.read()
            
        # Push to Fuseki default graph
        response = requests.put(
            FUSEKI_DATA_URL,
            data=data,
            headers={'Content-Type': 'application/rdf+xml'}
        )
        response.raise_for_status()
        return True, "Successfully synced local ontology to Fuseki."
    except Exception as e:
        return False, f"Sync Error: {e}"

# Dynamic Ontology Rule Cache
ONTOLOGY_CONSTRAINTS = {}
APPROVED_CLASSES = set()
REJECTED_CLASSES = set()

def load_ontology_constraints():
    """Extracts business rules and outcome hierarchies from the Fuseki SPARQL server."""
    global ONTOLOGY_CONSTRAINTS, APPROVED_CLASSES, REJECTED_CLASSES
    
    # 1. Fetch Class Restrictions
    sparql_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT ?class ?prop ?type ?value WHERE {
      ?class owl:equivalentClass ?equiv .
      ?equiv owl:intersectionOf/rdf:rest*/rdf:first ?restriction .
      ?restriction a owl:Restriction ; owl:onProperty ?prop .
      { ?restriction owl:hasValue ?value . BIND("hasValue" AS ?type) }
      UNION
      { ?restriction owl:someValuesFrom ?dt . ?dt owl:withRestrictions/rdf:rest*/rdf:first ?facet . ?facet ?type ?value . }
    }
    """
    data = query_fuseki(sparql_query)
    constraints = {}
    if data:
        for b in data['results']['bindings']:
            cls_name = b['class']['value'].split("#")[-1]
            prop = b['prop']['value'].split("#")[-1]
            op = b['type']['value'].split("#")[-1]
            val_raw = b['value']['value']
            datatype = b['value'].get('datatype', '')
            if 'integer' in datatype: val = int(val_raw)
            elif 'boolean' in datatype: val = val_raw.lower() == 'true'
            elif 'decimal' in datatype or 'float' in datatype: val = float(val_raw)
            else: val = val_raw
            if cls_name not in constraints: constraints[cls_name] = []
            constraints[cls_name].append({'prop': prop, 'type': op, 'val': val})
    ONTOLOGY_CONSTRAINTS = constraints

    # 2. Fetch Outcome Hierarchies
    hierarchy_query = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>
    SELECT ?class ?outcome WHERE {
      { ?class rdfs:subClassOf* loan:ApprovedOutcome . BIND("Approved" AS ?outcome) }
      UNION
      { ?class rdfs:subClassOf* loan:RejectedOutcome . BIND("Rejected" AS ?outcome) }
    }
    """
    h_data = query_fuseki(hierarchy_query)
    if h_data:
        APPROVED_CLASSES = {b['class']['value'] for b in h_data['results']['bindings'] if b['outcome']['value'] == "Approved"}
        REJECTED_CLASSES = {b['class']['value'] for b in h_data['results']['bindings'] if b['outcome']['value'] == "Rejected"}
    
    return constraints

# Initial load on startup
try:
    load_ontology_constraints()
except:
    pass

@app.route("/")
def index():
    return redirect(url_for('dashboard'))

@app.route("/schemes")
def get_schemes():
    """Fetches all loan schemes and their parent categories from Fuseki."""
    sparql_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>
    SELECT ?loanType ?label ?parent
    WHERE {
      ?loanType rdfs:subClassOf* loan:Loan .
      FILTER(?loanType != loan:Loan)
      OPTIONAL { ?loanType rdfs:label ?label }
      OPTIONAL {
        ?loanType rdfs:subClassOf ?parent .
        ?parent rdfs:subClassOf* loan:Loan .
        FILTER(?parent != loan:Loan && ?parent != ?loanType)
      }
    }
    """
    data = query_fuseki(sparql_query)
    schemes = {}
    
    if data:
        for b in data['results']['bindings']:
            uri = b['loanType']['value']
            name = b.get('label', {}).get('value') or uri.split("#")[-1]
            # Clean name for groups: EducationLoan -> Education, HousingLoan -> Housing
            clean_name = name.replace("Loan", "").strip()
            
            parent_uri = b.get('parent', {}).get('value')
            if not parent_uri:
                # Root category
                if clean_name not in schemes: schemes[clean_name] = []
            else:
                parent_name = parent_uri.split("#")[-1].replace("Loan", "").strip()
                if parent_name not in schemes: schemes[parent_name] = []
                # Don't add if it's the parent class itself (e.g. URI is HousingLoan)
                if uri.split("#")[-1] != parent_uri.split("#")[-1]:
                    if name not in schemes[parent_name]:
                        schemes[parent_name].append(name)
                        
    return jsonify(schemes)

@app.route("/sync-ontology", methods=["POST"])
def sync_ontology():
    success, message = sync_ontology_to_fuseki()
    return jsonify({"success": success, "message": message})

@app.route("/dashboard")
def dashboard():
    # 1. Fetch data from Fuseki using dynamic class resolution
    sparql_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>
    SELECT ?applicant ?label ?type ?loanType ?age ?income ?crib ?dti ?residency ?citizenship ?permanent ?arrears
    WHERE {
      ?applicant rdf:type ?type .
      ?type rdfs:subClassOf* loan:Applicant .
      FILTER(?type != <http://www.w3.org/2002/07/owl#NamedIndividual>)
      
      OPTIONAL { ?applicant rdfs:label ?label }
      OPTIONAL { ?applicant loan:hasAge ?age }
      OPTIONAL { ?applicant loan:hasMonthlyIncome ?income }
      OPTIONAL { ?applicant loan:hasCRIBScore ?crib }
      OPTIONAL { ?applicant loan:hasDTI ?dti }
      OPTIONAL { ?applicant loan:isResident ?residency }
      OPTIONAL { ?applicant loan:isSriLankan ?citizenship }
      OPTIONAL { ?applicant loan:isPermanentRole ?permanent }
      OPTIONAL { ?applicant loan:hasPreviousArrears ?arrears }

      OPTIONAL { 
        ?applicant loan:appliesFor ?loan .
        ?loan rdf:type ?loanType .
        ?loanType rdfs:subClassOf* loan:Loan .
        FILTER(?loanType != loan:Loan)
      }
    }
    """
    data = query_fuseki(sparql_query)
    
    onto_total = 0
    onto_rejected = 0
    onto_approved = 0
    onto_pending = 0
    
    distribution = {"Housing": 0, "Personal": 0, "Education": 0}
    
    if data:
        bindings = data.get('results', {}).get('bindings', [])
        applicant_map = {}
        for b in bindings:
            uri = b['applicant']['value']
            if uri not in applicant_map:
                applicant_map[uri] = {
                    'name': b.get('label', {}).get('value') or uri.split("#")[-1],
                    'types': set(),
                    'loans': set(),
                    'age': b.get('age', {}).get('value'),
                    'income': b.get('income', {}).get('value'),
                    'crib': b.get('crib', {}).get('value'),
                    'dti': b.get('dti', {}).get('value'),
                    'residency': b.get('residency', {}).get('value'),
                    'citizenship': b.get('citizenship', {}).get('value'),
                    'permanent': b.get('permanent', {}).get('value'),
                    'arrears': b.get('arrears', {}).get('value')
                }
            applicant_map[uri]['types'].add(b['type']['value'])
            if 'loanType' in b:
                applicant_map[uri]['loans'].add(b['loanType']['value'])

        onto_total = len(applicant_map)
        
        for uri, info in applicant_map.items():
            types = info['types']
            status_val = "Pending"
            name = info['name']
            
            # Hierarchical Status Detection
            is_approved = any(t in APPROVED_CLASSES for t in types)
            is_rejected = any(t in REJECTED_CLASSES for t in types)
            
            if is_approved:
                status_val = "Approved"
            elif is_rejected:
                status_val = "Rejected"
            else:
                # 1b. Logical Proxy Fallback for Dashboard Counts
                def get_bool(v):
                    if v is None: return None
                    return str(v).lower() == 'true'

                app_data = {
                    "hasAge": int(info['age']) if info.get('age') else None,
                    "hasMonthlyIncome": int(info['income']) if info.get('income') else None,
                    "hasCRIBScore": int(info['crib']) if info.get('crib') else None,
                    "hasDTI": float(info['dti']) if info.get('dti') else None,
                    "isResident": get_bool(info.get('residency')),
                    "isSriLankan": get_bool(info.get('citizenship')),
                    "isPermanentRole": get_bool(info.get('permanent')),
                    "hasPreviousArrears": get_bool(info.get('arrears'))
                }
                status_val, _ = perform_logical_assessment(app_data)

            if status_val == "Approved":
                onto_approved += 1
            elif status_val == "Rejected":
                onto_rejected += 1
            else:
                onto_pending += 1

            # Dynamic Loan Category Mapping
            found_category = False
            for lt in info['loans']:
                if "Housing" in lt or "Ithurum" in lt or "Siri" in lt:
                    distribution["Housing"] += 1
                    found_category = True
                    break
                elif "Education" in lt or "StudentLoan" in lt:
                    distribution["Education"] += 1
                    found_category = True
                    break
                elif "Personal" in lt or "Gold" in lt or "DiviDiriya" in lt or "VanithaAruna" in lt:
                    distribution["Personal"] += 1
                    found_category = True
                    break
            
            if not found_category:
                distribution["Personal"] += 1

    # Fetch dynamic metadata
    meta_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT (COUNT(?c) AS ?class_count) (COUNT(?p) AS ?prop_count)
    WHERE {
       { ?c a owl:Class } UNION { ?p a owl:ObjectProperty } UNION { ?p a owl:DatatypeProperty }
    }
    """
    meta_data = query_fuseki(meta_query)
    class_count = 42
    prop_count = 28
    if meta_data:
        try:
            class_count = int(meta_data['results']['bindings'][0]['class_count']['value'])
            prop_count = int(meta_data['results']['bindings'][0]['prop_count']['value'])
        except: pass

    history_approved = 0
    history_rejected = 0
    
    stats = {
        "total_rules": class_count, 
        "total_properties": prop_count, 
        "system_status": "Operational",
        "approved": onto_approved + history_approved,
        "rejected": onto_rejected + history_rejected,
        "pending": onto_pending,
        "distribution": distribution,
        "total_apps": onto_total
    }
    return render_template("dashboard.html", stats=stats)

@app.route("/applicant")
def applicant():
    return render_template("applicant.html")

@app.route("/status")
def status():
    sparql_query = """
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>
    SELECT ?applicant ?label ?type ?age ?income ?crib ?dti ?residency ?citizenship ?loanType ?permanent ?arrears ?university ?jewelry ?amount ?tenure ?purpose
    WHERE {
      ?applicant rdf:type ?type .
      ?type rdfs:subClassOf* loan:Applicant .
      FILTER(?type != <http://www.w3.org/2002/07/owl#NamedIndividual>)
      
      OPTIONAL { ?applicant rdfs:label ?label }
      OPTIONAL { ?applicant loan:hasAge ?age }
      OPTIONAL { ?applicant loan:hasMonthlyIncome ?income }
      OPTIONAL { ?applicant loan:hasCRIBScore ?crib }
      OPTIONAL { ?applicant loan:hasDTI ?dti }
      OPTIONAL { ?applicant loan:isResident ?residency }
      OPTIONAL { ?applicant loan:isSriLankan ?citizenship }
      OPTIONAL { ?applicant loan:isPermanentRole ?permanent }
      OPTIONAL { ?applicant loan:hasPreviousArrears ?arrears }
      OPTIONAL { ?applicant loan:isRecognizedInstitution ?university }
      OPTIONAL { ?applicant loan:hasJewelryCollateral ?jewelry }
      
      OPTIONAL { 
        ?applicant loan:appliesFor ?loan . 
        ?loan rdf:type ?loanType . 
        ?loanType rdfs:subClassOf* loan:Loan . 
        FILTER(?loanType != loan:Loan)
        
        OPTIONAL { ?loan loan:requestedLoanAmount ?amount }
        OPTIONAL { ?loan loan:hasLoanTenure ?tenure }
        OPTIONAL { ?loan rdfs:label ?purpose }
      }
    }
    """
    data = query_fuseki(sparql_query)
    ontology_history = []
    
    if data:
        bindings = data.get('results', {}).get('bindings', [])
        applicant_map = {}
        for b in bindings:
            uri = b['applicant']['value']
            if uri not in applicant_map:
                applicant_map[uri] = {
                    'name': b.get('label', {}).get('value') or uri.split("#")[-1],
                    'types': set(),
                    'loans': set(),
                    'age': b.get('age', {}).get('value'),
                    'income': b.get('income', {}).get('value'),
                    'crib': b.get('crib', {}).get('value'),
                    'dti': b.get('dti', {}).get('value'),
                    'residency': b.get('residency', {}).get('value'),
                    'citizenship': b.get('citizenship', {}).get('value'),
                    'permanent': b.get('permanent', {}).get('value'),
                    'arrears': b.get('arrears', {}).get('value'),
                    'university': b.get('university', {}).get('value'),
                    'jewelry': b.get('jewelry', {}).get('value'),
                    'amount': b.get('amount', {}).get('value'),
                    'tenure': b.get('tenure', {}).get('value'),
                    'purpose': b.get('purpose', {}).get('value')
                }
            applicant_map[uri]['types'].add(b['type']['value'])
            if 'loanType' in b:
                applicant_map[uri]['loans'].add(b['loanType']['value'])

        for uri, info in applicant_map.items():
            name = info['name']
            types = info['types']
            
            # 1. Hierarchical Status Detection
            status_val = "Pending"
            reason = "Awaiting Reasoning Outcome"
            
            relevant_rejections = [t for t in types if t in REJECTED_CLASSES]
            relevant_approvals = [t for t in types if t in APPROVED_CLASSES]
            
            if relevant_approvals:
                status_val = "Approved"
                reason = "Met all ontological safety and eligibility criteria."
            elif relevant_rejections:
                status_val = "Rejected"
                spec_rej = relevant_rejections[0].split("#")[-1]
                import re
                reason = re.sub(r'([A-Z])', r' \1', spec_rej).strip()
            else:
                # 1b. Fallback to Logical Proxy for individual data
                def get_bool(v):
                    if v is None: return None
                    return str(v).lower() == 'true'

                app_data = {
                    "hasAge": int(info['age']) if info['age'] else None,
                    "hasMonthlyIncome": int(info['income']) if info['income'] else None,
                    "hasCRIBScore": int(info['crib']) if info['crib'] else None,
                    "hasDTI": float(info['dti']) if info['dti'] else None,
                    "isResident": get_bool(info.get('residency')),
                    "isSriLankan": get_bool(info.get('citizenship')),
                    "isPermanentRole": get_bool(info.get('permanent')),
                    "hasPreviousArrears": get_bool(info.get('arrears')),
                    "isRecognizedInstitution": get_bool(info.get('university')),
                    "hasJewelryCollateral": get_bool(info.get('jewelry'))
                }
                status_val, reason = perform_logical_assessment(app_data)
            
            # 2. Dynamic Employment and Loan type
            emp_type = "Applicant"
            for et in ["SalariedEmployee", "SelfEmployed", "Retiree", "Student"]:
                if any(et in t for t in types):
                    emp_type = et
                    break
            
            loan_type_str = list(info['loans'])[0].split("#")[-1] if info['loans'] else "General"

            # 3. Data Formatting
            res = info['residency']
            cit = info['citizenship']
            
            ontology_history.append({
                "name": name,
                "loanType": loan_type_str,
                "diagnosis": status_val,
                "category": reason,
                "details": {
                    "age": str(info['age']) if info['age'] else "N/A",
                    "income": f"LKR {int(info['income']):,}" if info['income'] else "N/A",
                    "crib": str(info['crib']) if info['crib'] else "Not Checked",
                    "dti": f"{float(info['dti'])*100:.1f}%" if info['dti'] else "N/A",
                    "residency": "Resident" if str(res).lower() == "true" else "Non-Resident",
                    "citizenship": "Sri Lankan" if str(cit).lower() == "true" else "Other",
                    "employment": emp_type.replace("Employee", " Employee"),
                    "requested": f"LKR {int(info['amount']):,}" if info.get('amount') else "N/A",
                    "tenure": f"{info['tenure']} Months" if info.get('tenure') else "N/A",
                    "purpose": info.get('purpose') or "General Finance"
                },
                "source": "Ontology"
            })

    full_history = ontology_history
    full_history.sort(key=lambda x: x.get('name'))

    return render_template("status.html", history=full_history)

@app.route("/predictor")
def predictor():
    return render_template("predictor.html")

@app.route("/evaluate", methods=["POST"])
def evaluate():
    data = request.json
    
    # 1. Extraction from Nested Structure
    meta = data.get("meta", {})
    prof = data.get("professional", {})
    fin = data.get("financial", {})
    loan_p = data.get("loan", {})
    dyn = data.get("dynamic", {})

    name = meta.get("name", "Unknown Applicant")
    
    # Map raw data to property names used in OWL
    applicant_data = {
        "isSriLankan": meta.get("isSriLankan", True),
        "isResident": meta.get("residency") == "Resident",
        "hasMonthlyIncome": int(fin.get("income", 0)),
        "hasDTI": float(fin.get("dti", 0.0)),
        "hasCRIBScore": int(fin.get("crib", 0)),
        "hasPreviousArrears": fin.get("hasArrears", False),
        "isPermanentRole": prof.get("isPermanent", True),
        "hasAL3Passes": dyn.get("alPasses", False),
        "isRecognizedInstitution": dyn.get("isRecognized", False),
        "hasClearTitle": dyn.get("clearTitle", False),
        "requestedLoanAmount": int(loan_p.get("amount", 0)),
        "hasJewelryCollateral": dyn.get("hasJewelry", False),
        "hasPensionProof": prof.get("type") == "Retired"
    }

    diagnosis = "Approved"
    category = "Eligible"
    details = []

    # 2. Dynamic Evaluation using Ontology Constraints (Logical Proxy)
    rejections_found = []
    if not ONTOLOGY_CONSTRAINTS: load_ontology_constraints()
    
    for rej_class, rules in ONTOLOGY_CONSTRAINTS.items():
        if "Rejection" not in rej_class and "Applicant" not in rej_class: continue
        if "Approved" in rej_class: continue
        
        matches_all_rules = True
        for rule in rules:
            prop = rule['prop']
            val = applicant_data.get(prop)
            target = rule['val']
            op = rule['type']
            
            if val is None: 
                matches_all_rules = False
                break
                
            if op == 'hasValue':
                if val != target: matches_all_rules = False
            elif op == 'minInclusive':
                if not (val >= target): matches_all_rules = False
            elif op == 'maxInclusive':
                if not (val <= target): matches_all_rules = False
            elif op == 'minExclusive':
                if not (val > target): matches_all_rules = False
            elif op == 'maxExclusive':
                if not (val < target): matches_all_rules = False
            
            if not matches_all_rules: break
            
        if matches_all_rules:
            readable_rej = re.sub(r'([A-Z])', r' \1', rej_class).strip()
            rejections_found.append(readable_rej)
            details.append(f"Fails '{readable_rej}' restriction.")

    if rejections_found:
        diagnosis = "Rejected"
        category = rejections_found[0]
    
    # 3. Persistent Storage via SPARQL UPDATE
    import uuid
    app_id = f"App_{uuid.uuid4().hex[:8]}"
    
    # Determine the specific type for individual assertion
    # If rejected, we assert the rejection class as one of its types
    rdf_types = ["loan:Applicant"]
    
    # Add employment type as a class
    emp_type = prof.get("type", "Salaried")
    if emp_type == "Salaried": rdf_types.append("loan:SalariedEmployee")
    elif emp_type == "Self-Employed": rdf_types.append("loan:SelfEmployed")
    elif emp_type == "Retired": rdf_types.append("loan:Retiree")
    elif emp_type == "Student": rdf_types.append("loan:Student")

    if diagnosis == "Rejected" and rejections_found:
        # Use first rejection class for direct typing
        spec_type = f"loan:{rejections_found[0].replace(' ', '')}"
        if spec_type not in rdf_types: rdf_types.append(spec_type)
    else:
        rdf_types.append("loan:ApprovedApplicant")

    # Construct Triples for Applicant
    triples = [
        f'loan:{app_id} rdf:type {", ".join(rdf_types)}',
        f'loan:{app_id} rdfs:label "{name}"',
        f'loan:{app_id} loan:hasAge {meta.get("age", 30)}',
        f"loan:{app_id} loan:hasMonthlyIncome {applicant_data['hasMonthlyIncome']}",
        f"loan:{app_id} loan:hasDTI {applicant_data['hasDTI']}",
        f"loan:{app_id} loan:hasCRIBScore {applicant_data['hasCRIBScore']}",
        f"loan:{app_id} loan:isResident {str(applicant_data['isResident']).lower()}",
        f"loan:{app_id} loan:isSriLankan {str(applicant_data['isSriLankan']).lower()}",
        f"loan:{app_id} loan:hasPreviousArrears {str(applicant_data['hasPreviousArrears']).lower()}",
        f"loan:{app_id} loan:isPermanentRole {str(applicant_data['isPermanentRole']).lower()}"
    ]

    # Add dynamic/conditional properties
    if applicant_data['hasPensionProof']:
        triples.append(f"loan:{app_id} loan:hasPensionProof true")
    if applicant_data['hasAL3Passes']:
        triples.append(f"loan:{app_id} loan:hasAL3Passes true")
    if applicant_data['isRecognizedInstitution']:
        triples.append(f"loan:{app_id} loan:isRecognizedInstitution true")
    if applicant_data['hasJewelryCollateral']:
        triples.append(f"loan:{app_id} loan:hasJewelryCollateral true")
    if applicant_data['hasClearTitle']:
        triples.append(f"loan:{app_id} loan:hasClearTitle true")

    # Create a Loan individual
    loan_id = f"Loan_{uuid.uuid4().hex[:8]}"
    loan_type = loan_p.get("type", "Personal")
    loan_sub_type = loan_p.get("subType", f"{loan_type} Loan")
    
    # Map subType to ontology class if possible, else use parent type
    onto_loan_class = f"loan:{loan_sub_type.replace(' ', '')}"
    if "Loan" not in onto_loan_class: onto_loan_class += "Loan"

    loan_triples = [
        f'loan:{loan_id} rdf:type {onto_loan_class}',
        f'loan:{loan_id} rdfs:label "{loan_sub_type} for {name}"',
        f'loan:{loan_id} loan:requestedLoanAmount {applicant_data["requestedLoanAmount"]}',
        f'loan:{loan_id} loan:hasLoanTenure {loan_p.get("tenure", 60)}'
    ]

    # Link Applicant to Loan
    triples.append(f"loan:{app_id} loan:appliesFor loan:{loan_id}")

    update_query = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>
    INSERT DATA {{
      { " . ".join(triples) } .
      { " . ".join(loan_triples) } .
    }}
    """
    update_fuseki(update_query)

    return jsonify({
        "diagnosis": diagnosis,
        "category": category,
        "details": details
    })

@app.route("/predict", methods=["POST"])
def predict():
    data = request.json
    age = int(data.get("age", 30))
    salary = int(data.get("salary", 0))
    expenses = int(data.get("expenses", 0))
    amount = int(data.get("amount", 0))
    duration = int(data.get("duration", 0))
    employment = data.get("employment", "Salaried")
    crib = data.get("crib", "Good")
    purpose = data.get("purpose", "Personal")
    collateral = data.get("collateral", [])
    is_female = data.get("isFemale", False)
    has_al = data.get("hasALPasses", False)
    
    # 1. Map UI Inputs to property names for evaluating constraints
    applicant_data = {
        "isSriLankan": True,
        "isResident": True,
        "hasMonthlyIncome": salary,
        "hasDTI": expenses / salary if salary > 0 else 0,
        "hasCRIBScore": 800 if crib == "Excellent" else (600 if crib == "Good" else 400),
        "hasPreviousArrears": crib == "Poor",
        "hasAL3Passes": has_al,
        "isFemale": is_female,
        "hasJewelryCollateral": "Gold" in collateral,
        "hasFDCollateral": "FD" in collateral,
        "hasAge": age,
        "hasLoanTenure": duration
    }

    # 2. Dynamic Recommendation Logic (Driven by Ontology)
    best_loan = f"NSB {purpose} Loan"
    score = 85
    justification = f"Based on your {employment} profile and need for {purpose} financing."
    
    # Check Rejection constraints specifically
    rejections = []
    if not ONTOLOGY_CONSTRAINTS: load_ontology_constraints()
    
    for rej_class, rules in ONTOLOGY_CONSTRAINTS.items():
        # Only check rejections relevant to this category if possible, or all for safety
        if "Rejection" in rej_class or "Rejected" in rej_class:
            matches = True
            for rule in rules:
                val = applicant_data.get(rule['prop'])
                if val is None: continue
                target = rule['val']
                op = rule['type']
                if op == 'hasValue' and val != target: matches = False
                elif op == 'minInclusive' and val < target: matches = False
                elif op == 'maxInclusive' and val > target: matches = False
                elif op == 'minExclusive' and val <= target: matches = False
                elif op == 'maxExclusive' and val >= target: matches = False
                if not matches: break
            if matches:
                rejections.append(re.sub(r'([A-Z])', r' \1', rej_class).strip())

    if rejections:
        score = 40
        justification = f"WARNING: Our ontology identifies potential conflicts: {', '.join(rejections)}. Please ensure you meet all mandatory criteria."

    # Specific Recommendation
    if "FD" in collateral:
        best_loan = "NSB FD-Backed Loan"
        score = 98
    elif "Gold" in collateral and amount < 500000:
        best_loan = "Pawning / Gold Loan"
        score = 95
    elif purpose == "Education" and has_al and age <= 25:
        best_loan = "Interest Free Student Loan (IFSLS)"
        score = 92
    elif purpose == "Personal" and is_female:
        best_loan = "Vanitha Aruna"
        score = 90

    # 3. Document & Security Mapping (Static for now, but linked to Loan types)
    docs = ["NIC Copy", "Income Proof"]
    sec = ["Standard Security"]
    
    if "Housing" in best_loan:
        docs += ["Deed", "Plan"]
        sec = ["Property Mortgage"]
    elif "Gold" in best_loan:
        docs += ["Gold Items"]
        sec = ["Gold Collateral"]

    return jsonify({
        "recommended_loan": best_loan,
        "description": f"Targeted {purpose} solution driven by ontology logic.",
        "documents": docs,
        "security": sec,
        "justification": justification,
        "score": score
    })

@app.route("/sparql")
def sparql_terminal():
    return render_template("sparql.html")

@app.route("/execute-sparql", methods=["POST"])
def execute_sparql():
    query = request.json.get("query")
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    try:
        data = query_fuseki(query)
        if not data:
            return jsonify({"error": "Failed to communicate with Fuseki server."}), 500
        
        # Fuseki returns vars in 'head' and results in 'results'
        vars = data.get('head', {}).get('vars', [])
        bindings = data.get('results', {}).get('bindings', [])
        
        # Format results into a list of dictionaries
        formatted_results = []
        for binding in bindings:
            item = {}
            for var in vars:
                # binding[var] is an object like {'type': 'uri', 'value': '...'}
                val_obj = binding.get(var, {})
                val_str = val_obj.get('value', '')
                
                # Clean up URIs for display
                if "#" in val_str:
                    val_str = val_str.split("#")[-1]
                item[var] = val_str
            formatted_results.append(item)
            
        return jsonify({
            "vars": vars,
            "results": formatted_results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(debug=True, port=5000)
