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
        "nombre": "Beneficio bruto", "unit": "USD", "combine": False, "opcional": True,
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
    # Componentes de las amortizaciones para compañías que no usan la etiqueta
    # combinada (Broadcom, Alphabet): D&A = depreciación + amortización de intangibles.
    "depreciacion": {
        "nombre": "Depreciación", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["Depreciation", "DepreciationNonproduction"],
    },
    "amort_intangibles": {
        "nombre": "Amortización de intangibles", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["AmortizationOfIntangibleAssets", "AmortizationOfAcquiredIntangibleAssets"],
    },
    "impuestos": {
        "nombre": "Impuesto sobre beneficios", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["IncomeTaxExpenseBenefit"],
    },
    "beneficio_antes_impuestos": {
        "nombre": "Beneficio antes de impuestos", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                 "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                 "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    },
    "otros_no_operativos": {
        "nombre": "Otros ingresos (gastos) no operativos", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"],
    },
    "ganancias_inversiones": {
        "nombre": "Ganancias (pérdidas) en participaciones", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["EquitySecuritiesFvNiGainLoss", "EquitySecuritiesFvNiUnrealizedGainLoss"],
    },
    "coste_ventas": {
        "nombre": "Coste de ventas", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    },
    "gastos_intereses": {
        "nombre": "Gastos por intereses", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    },
    "dividendos": {
        "nombre": "Dividendos pagados", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    },
    # I+D. Amazon no publica I+D: su «Technology and infrastructure» (antes
    # «Technology and content») es lo más parecido y se etiqueta con su propia taxonomía.
    "investigacion_desarrollo": {
        "nombre": "Investigación y desarrollo (I+D)", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["ResearchAndDevelopmentExpense",
                 "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
                 "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost",
                 "*:TechnologyAndInfrastructureExpense", "*:TechnologyAndContentExpense",
                 "*:TechnologyAndDevelopmentExpense", "*:ResearchAndDevelopmentExpense"],
    },
    # Gastos comerciales y de administración (Beneish M). Algunas compañías los
    # dan juntos (SG&A) y otras por separado (ventas y marketing + generales).
    "gastos_generales": {
        "nombre": "Gastos comerciales y de administración (SG&A)", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["SellingGeneralAndAdministrativeExpense"],
    },
    "ventas_marketing": {
        "nombre": "Ventas y marketing", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["SellingAndMarketingExpense", "MarketingAndAdvertisingExpense"],
    },
    "gastos_admin": {
        "nombre": "Gastos generales y de administración", "unit": "USD", "combine": True, "opcional": True,
        "tags": ["GeneralAndAdministrativeExpense"],
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
             "optional": [["LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent", "ShortTermBorrowings"]]},
            # Chevron (10-Q): deuda a largo con vencimientos corrientes incluidos + deuda a corto
            {"required": ["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"],
             "optional": [["ShortTermBorrowings", "CommercialPaper"]]},
            {"required": ["ConvertibleNotesPayable"],
             "optional": [["ConvertibleNotesPayableCurrent"]]},
            # Moderna (3T26): convertibles + préstamo dispuesto de la línea de crédito, sin etiqueta de deuda total
            {"required": ["ConvertibleLongTermNotesPayable"],
             "optional": [["LongTermLineOfCredit", "LongTermDebtNoncurrent", "LongTermLoansPayable"],
                          ["ConvertibleNotesPayableCurrent", "LongTermDebtCurrent", "DebtCurrent"]]},
            {"required": ["SeniorLongTermNotes"], "optional": []},
            # Oracle: pagarés y préstamos a largo + pagarés corrientes (10-Q); en el 10-K, LongTermNotesPayable
            {"required": ["LongTermNotesAndLoans"],
             "optional": [["NotesPayableCurrent", "DebtCurrent"]]},
            {"required": ["LongTermNotesPayable"],
             "optional": [["NotesPayableCurrent", "DebtCurrent"]]},
            {"required": ["LongTermLineOfCredit"], "optional": [["LineOfCredit", "DebtCurrent"]]},
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
    "activo_corriente": {
        "nombre": "Activo corriente", "opcional": True,
        "strategies": [{"required": ["AssetsCurrent"], "optional": []}],
    },
    "pasivo_corriente": {
        "nombre": "Pasivo corriente", "opcional": True,
        "strategies": [{"required": ["LiabilitiesCurrent"], "optional": []}],
    },
    "existencias": {
        "nombre": "Existencias", "opcional": True,
        "strategies": [{"required": ["InventoryNet"], "optional": []}],
    },
    # Para las puntuaciones de calidad (Piotroski, Altman Z, Beneish M)
    "pasivo_total": {
        "nombre": "Pasivo total", "opcional": True,
        "strategies": [{"required": ["Liabilities"], "optional": []}],
    },
    "beneficios_retenidos": {
        "nombre": "Beneficios retenidos", "opcional": True,
        "strategies": [{"required": ["RetainedEarningsAccumulatedDeficit"], "optional": []}],
    },
    "cuentas_cobrar": {
        "nombre": "Cuentas a cobrar", "opcional": True,
        "strategies": [{"required": ["AccountsReceivableNetCurrent"], "optional": []},
                       {"required": ["ReceivablesNetCurrent"], "optional": []},
                       {"required": ["AccountsNotesAndLoansReceivableNetCurrent"], "optional": []}],
    },
    "inmovilizado": {
        "nombre": "Inmovilizado material neto", "opcional": True,
        "strategies": [{"required": ["PropertyPlantAndEquipmentNet"], "optional": []},
                       {"required": ["PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"], "optional": []}],
    },
}

# Calendario de vencimientos de la deuda (nota de deuda del 10-K/10-Q).
DEBT_MATURITY_TAGS = [
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalRemainderOfFiscalYear", "Resto del ejercicio"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths", "Año 1"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo", "Año 2"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree", "Año 3"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour", "Año 4"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive", "Año 5"),
    ("LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive", "Después del año 5"),
]

SHARES_OUTSTANDING_TAG = ("dei", "EntityCommonStockSharesOutstanding")
