# SPARQL Query Reference

This document details the SPARQL queries designed to answer the project's competency questions. These queries demonstrate advanced features such as mathematical BINDings, FILTERing, and hierarchical reasoning.

## 1. Applicant Reasoning (Defeasible Logic)

**Purpose:** Identify applicants who have been classified into specific rejection or pending categories by the OWL Reasoner.

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>

SELECT ?applicant ?pendingReason
WHERE {
  # Get applicants classified into specific pending sub-classes
  ?applicant rdf:type ?pendingReason .

  # Filter only the specific rejection classes
  FILTER(?pendingReason IN (
    loan:AgeRestrictedApplicant,
    loan:LowIncomeApplicant,
    loan:HighRiskApplicant
  ))
}
```

## 2. Loan-To-Value (LTV) Validation

**Purpose:** Dynamically calculate the LTV ratio for Housing Loans and apply a 70% threshold policy.

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>

SELECT ?applicant ?requestedAmount ?propertyValue ?LTV_Ratio ?LTV_Status
WHERE {
  ?applicant rdf:type loan:Applicant .
  ?applicant loan:appliesFor ?loan .
  ?loan rdf:type loan:HousingLoan .
  ?loan loan:requestedLoanAmount ?requestedAmount .

  ?applicant loan:hasCollateral ?property .
  ?property loan:hasValuationAmount ?propertyValue .

  # Calculate LTV Ratio dynamically -> (Request / Value)
  BIND(xsd:decimal(?requestedAmount) / xsd:decimal(?propertyValue) AS ?LTV_Ratio)

  # Bank Policy: If LTV > 0.70 (70%), the loan is Too Risky
  BIND(IF(?LTV_Ratio > 0.70, "REJECTED - LTV Too High", "APPROVED - LTV Acceptable") AS ?LTV_Status)
}
ORDER BY ?LTV_Status
```

## 3. Geolocation Risk Assessment

**Purpose:** Filter collateral properties located in districts with high environmental risks (e.g., Flood Zones).

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>

SELECT ?applicant ?property ?district
WHERE {
  ?applicant rdf:type loan:Applicant .
  ?applicant loan:hasCollateral ?property .
  ?property loan:locatedInDistrict ?district .

  # Only select applicants whose property is in a flood zone
  FILTER(?district = loan:FloodZoneDistrict)
}
```

## 4. Master Application Pipeline

**Purpose:** A comprehensive query evaluating Age, Income, Arrears, LTV, and Geolocation simultaneously to determine a final approval status.

```sparql
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX loan: <http://www.semanticweb.org/ontology/loan_approval#>

SELECT ?applicant ?age ?loanType ?FinalStatus
WHERE {
  ?applicant rdf:type loan:Applicant .
  ?applicant loan:hasAge ?age .
  ?applicant loan:hasMonthlyIncome ?income .
  ?applicant loan:hasPreviousArrears ?arrears .

  ?applicant loan:appliesFor ?loan .
  ?loan rdf:type ?loanType .
  FILTER(?loanType != owl:NamedIndividual && ?loanType != loan:Loan)

  # Optional: Get LTV values if it is a Housing Loan
  OPTIONAL {
    ?loan loan:requestedLoanAmount ?requestedAmount .
    ?applicant loan:hasCollateral ?property .
    ?property loan:hasValuationAmount ?propertyValue .
    ?property loan:locatedInDistrict ?district .
  }

  # Calculate LTV Ratio
  BIND(xsd:decimal(?requestedAmount) / xsd:decimal(?propertyValue) AS ?LTV_Ratio)

  # Complex Business Logic:
  BIND(
    # 1. Base requirements (Age, Income, No Arrears)
    IF(?age >= 18 && ?age <= 60 && ?income > 30000 && ?arrears = false,

       # 2. If it is a Housing Loan, perform LTV and Region checks
       IF(?loanType = loan:HousingLoan,
          IF(?LTV_Ratio <= 0.70 && ?district != loan:FloodZoneDistrict, "Fully Approved",
             IF(?LTV_Ratio > 0.70, "Declined - LTV over limit", "Declined - High Risk Flood Zone")),

          # If not a housing loan, they pass the base requirements
          "Fully Approved"),

       "Declined - Failed Base Requirements (Age/Income/Arrears)"
    )
  AS ?FinalStatus)
}
ORDER BY ?applicant
```
