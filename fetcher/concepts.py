"""Catálogo de conceptos financieros y sus etiquetas XBRL candidatas.

Orden de las etiquetas = preferencia cuando dos etiquetas igual de recientes
cubren el mismo periodo. En la práctica manda la recencia: primero la etiqueta
cuyo último dato es más reciente (ver extract.order_tags).

kind:
  flow    -> magnitud de periodo (cuenta de resultados, flujos de caja)
  instant -> saldo a una fecha (balance)
combine:
  True  -> se combinan etiquetas por periodo (p. ej. ingresos: SalesRevenueNet
           hasta 2017, Revenues después, RevenueFromContract... hoy).
  False -> una sola etiqueta: la primera que no esté obsoleta.
"""

GAAP = "us-gaap"
DEI = "dei"

FLOW_CONCEPTS = {
    "ingresos": {
        "nombre": "Ingresos", "unit": "USD", "combine": True,
        "tags": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
    },
    "beneficio_bruto": {
        "nombre": "Beneficio bruto", "unit": "USD", "combine": False,
        "tags": ["GrossProfit"],
    },
    "beneficio_operativo": {
        "nombre": "Beneficio operativo", "unit": "USD", "combine": False,
        "tags": ["OperatingIncomeLoss"],
    },
    "beneficio_neto": {
        "nombre": "Beneficio neto", "unit": "USD", "combine": False,
        "tags": ["NetIncomeLoss", "ProfitLoss"],
    },
    "bpa_diluido": {
        "nombre": "BPA diluido", "unit": "USD/shares", "combine": False,
        "tags": ["EarningsPerShareDiluted"], "no_sum": True,
    },
    "acciones_diluidas_media": {
        "nombre": "Acciones diluidas (media)", "unit": "shares", "combine": False,
        "tags": ["WeightedAverageNumberOfDilutedSharesOutstanding"], "no_sum": True,
    },
    "caja_operativa": {
        "nombre": "Flujo de caja operativo", "unit": "USD", "combine": True,
        "tags": [
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
    },
    "capex": {
        "nombre": "Capex", "unit": "USD", "combine": True,
        "tags": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ],
    },
    "amortizacion": {
        "nombre": "Amortizaciones (D&A)", "unit": "USD", "combine": True,
        "tags": [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
        ],
    },
    "remuneracion_acciones": {
        "nombre": "Remuneración en acciones (SBC)", "unit": "USD", "combine": True,
        "tags": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    },
    "recompras": {
        "nombre": "Recompras de acciones", "unit": "USD", "combine": True,
        "tags": ["PaymentsForRepurchaseOfCommonStock"],
    },
}

# Saldos de balance. Cada concepto tiene «estrategias»: listas de componentes
# que se suman en la misma fecha. «required» = el componente principal; los
# opcionales cuentan 0 si no existen para esa fecha (y se avisa).
INSTANT_CONCEPTS = {
    "caja": {
        "nombre": "Caja e inversiones a corto",
        "strategies": [
            {"required": ["CashCashEquivalentsAndShortTermInvestments"], "optional": []},
            {"required": ["CashAndCashEquivalentsAtCarryingValue"],
             "optional": [["ShortTermInvestments", "MarketableSecuritiesCurrent",
                           "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]]},
            {"required": ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], "optional": []},
        ],
    },
    "deuda": {
        "nombre": "Deuda financiera",
        "strategies": [
            {"required": ["LongTermDebtNoncurrent"],
             "optional": [["LongTermDebtCurrent", "DebtCurrent"]]},
            {"required": ["LongTermDebt"], "optional": []},
            {"required": ["LongTermDebtAndCapitalLeaseObligations"],
             "optional": [["LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent"]]},
            {"required": ["ConvertibleNotesPayable"],
             "optional": [["ConvertibleNotesPayableCurrent"]]},
            {"required": ["SeniorLongTermNotes"], "optional": []},
        ],
        "assume_zero_if_missing": True,
    },
    "patrimonio_neto": {
        "nombre": "Patrimonio neto",
        "strategies": [
            {"required": ["StockholdersEquity"], "optional": []},
            {"required": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "optional": []},
        ],
    },
    "activo_total": {
        "nombre": "Activo total",
        "strategies": [{"required": ["Assets"], "optional": []}],
    },
}

SHARES_OUTSTANDING_TAG = ("dei", "EntityCommonStockSharesOutstanding")
