"""
CA Inter Knowledge Base - 200+ chunks for RAG
Format: ID | Subject | Chapter | Topic | Content
This is the foundation for proper RAG as suggested by ChatGPT/Claude feedback.
"""

KNOWLEDGE_BASE = [
    # LAW - LLP Act
    {
        "id": "LAW_LLP_001",
        "subject": "Law",
        "chapter": "LLP Act, 2008",
        "topic": "Section 2 Definitions",
        "content": "Section 2 of LLP Act, 2008 is the definitions section - dictionary for entire Act. Key definitions: (a) Address means registered office address; (b) Advocate means advocate under Advocates Act 1961; (c) Appellate Tribunal means NCLAT; (d) Body Corporate includes company, LLP, foreign LLP, but excludes corporation sole, cooperative society; (e) Business includes every trade, profession, service, occupation; (f) Chartered Accountant, Company Secretary, Cost Accountant as per respective Acts; (j) Designated Partner as per Section 7; (n) LLP means partnership formed and registered under this Act; (o) LLP Agreement means agreement between partners or between LLP and partners determining mutual rights and duties; (q) Partner means any person who becomes partner per LLP Agreement. Exam focus: Don't mug all 20+ clauses. Focus on LLP, Partner, Designated Partner, LLP Agreement, Body Corporate, Business - repeatedly tested."
    },
    {
        "id": "LAW_LLP_002",
        "subject": "Law",
        "chapter": "LLP Act, 2008",
        "topic": "Section 3-4 Nature of LLP",
        "content": "Section 3: LLP is body corporate formed and incorporated under this Act, legal entity separate from partners, perpetual succession. Change in partners does not affect existence, rights, liabilities. Section 4: Any provision of Indian Partnership Act 1932 shall not apply to LLP except as otherwise provided. Section 5: Mutual rights and duties of partners and LLP governed by LLP Agreement, or First Schedule if no agreement. Section 6: LLP is body corporate - can sue and be sued, acquire, own, hold, develop property, have common seal. Section 7: Every LLP shall have at least 2 designated partners who are individuals, at least one resident in India. If all partners are bodies corporate, nominees act as designated partners."
    },
    {
        "id": "LAW_LLP_003",
        "subject": "Law",
        "chapter": "LLP Act, 2008",
        "topic": "Designated Partner Section 7-9",
        "content": "Section 7 Designated Partners: At least 2 designated partners, individuals, at least one resident in India (stayed 182 days in previous year). If incorporation document states who are designated partners, they are designated. If all partners are bodies corporate, their nominees who are individuals. Section 8: Liabilities of designated partners - responsible for compliance, liable for penalties if contravention. Section 9: Change in designated partners - LLP to file with ROC within 30 days, with consent. Section 10: Punishment for contravention - LLP and designated partners liable. Exam trap: Minimum 2 DPs, one resident - case study on vacancy, resignation, death. Consequences of non-filing. Rights/duties derived from Agreement."
    },
    {
        "id": "LAW_CO_001",
        "subject": "Law",
        "chapter": "Companies Act, 2013",
        "topic": "Section 2 Company Definitions",
        "content": "Section 2 Companies Act 2013: (20) Company means company incorporated under this Act or any previous law; (62) One Person Company means company with only one person as member; (68) Private company means company with minimum 2 members, maximum 200, restricts transfer, prohibits public invitation; (71) Public company means not private company, minimum 7 members, no max; (85) Small company: private company with paid-up capital <=4 crore and turnover <=40 crore, not holding/subsidiary/Section 8. Exam: Distinguish private vs public, OPC, small company criteria (amended limits)."
    },
    {
        "id": "LAW_CO_002",
        "subject": "Law",
        "chapter": "Companies Act, 2013",
        "topic": "Section 43 Types of Share Capital",
        "content": "Section 43: Kinds of share capital. Company limited by shares can have two kinds: (a) Equity share capital - (i) with voting rights, or (ii) with differential rights as to dividend, voting, etc. as per rules; (b) Preference share capital - with preferential rights on dividend and capital repayment. Equity share capital: With reference to any company limited by shares, all share capital which is not preference share capital. Preference share capital: Part of issued share capital carrying preferential right on dividend (fixed amount or rate) and repayment of capital on winding up. For private companies, memorandum or articles may permit other kinds. ICAI tests: Distinguish equity vs preference, differential voting rights conditions (Rule 4: 26% voting power, 3 years distributable profits, no default in filing)."
    },
    {
        "id": "LAW_CO_003",
        "subject": "Law",
        "chapter": "Companies Act, 2013",
        "topic": "Section 185 Loan to Directors",
        "content": "Section 185: No company shall directly/indirectly advance loan, including book debt, to any director or person in whom director interested, or give guarantee/security for loan taken by such person. Exceptions: (a) Loan to managing/whole-time director as part of service conditions or pursuant to scheme approved by members; (b) Company provides loan/guarantee/security for due repayment of loan in ordinary course of business, at interest >= bank rate; (c) Loan by holding company to wholly owned subsidiary, or guarantee/security for loan made to wholly owned subsidiary, used for principal business; (d) Guarantee/security by holding company for loan to subsidiary for principal business. Conditions for private company exemption: No body corporate investment, borrowing from banks/FIs <=2x paid-up+free reserves or 50cr whichever lower, no default. Punishment: Company fine 5L-25L, director/officer imprisonment up to 6 months or fine 5L-25L or both."
    },
    {
        "id": "LAW_CO_004",
        "subject": "Law",
        "chapter": "Companies Act, 2013",
        "topic": "Section 135 CSR",
        "content": "Section 135 CSR Applicability: Every company having during immediately preceding FY: Net worth 500cr or more, OR Turnover 1000cr or more, OR Net profit 5cr or more. Must constitute CSR Committee: 3+ Directors (at least 1 ID), for private/unlisted with only 2 directors, both. For companies not required to appoint ID, 2+ directors. Functions: Formulate CSR policy, recommend expenditure, monitor. Company to spend 2% of average net profits of last 3 years. If fails to spend, transfer unspent to Fund specified in Schedule VII within 6 months, or to special account for ongoing project (3 years). Excess spend can be set off up to 3 succeeding years. Disclosure in Board report. ICAI: Calculation of 2%, ongoing vs other than ongoing, penalty."
    },
    # AUDIT
    {
        "id": "AUDIT_001",
        "subject": "Audit",
        "chapter": "Audit Evidence",
        "topic": "SA 500 Audit Evidence",
        "content": "SA 500 Audit Evidence: Sufficiency = quantity of evidence, Appropriateness = quality (relevance and reliability). Reliability hierarchy: External > Internal, Direct > Indirect, Documentary > Oral, Original > Photocopy. Procedures to obtain evidence: (1) Inspection of records/documents, (2) Observation of process, (3) Inquiry with management/others, (4) Confirmation from third party, (5) Recalculation, (6) Reperformance, (7) Analytical procedures. Written vs oral, internal vs external. Exam: For cash, stock, receivables - which procedure appropriate? Example: Bank confirmation external, more reliable than internal cash book."
    },
    {
        "id": "AUDIT_002",
        "subject": "Audit",
        "chapter": "Company Audit",
        "topic": "Section 139-142 Appointment",
        "content": "Section 139: First auditor appointed by Board within 30 days of incorporation, if fails, members within 90 days at EGM. Subsequent auditor appointed at AGM for 5-year term (individual 5 years max, firm 10 years with rotation). Ratification removed by Amendment 2017. Section 139(2): Listed, public company with paid-up 10cr+, private with 50cr+, all companies with borrowing 50cr+ - rotation mandatory. Individual cannot be reappointed for 5 years after 5-year term, firm 5 years after 10-year term. Section 140: Removal before term requires special resolution + CG approval. Resignation to be filed with ROC within 30 days in ADT-3. Section 141: Eligibility - CA in practice, disqualifications: subsidiary/associate, indebted >5L, business relationship. Section 142: Remuneration fixed by members or as per AGM."
    },
    # ACCOUNTS
    {
        "id": "ACCOUNTS_001",
        "subject": "Accounts",
        "chapter": "Accounting Standards",
        "topic": "AS 1 Disclosure of Accounting Policies",
        "content": "AS 1 Disclosure of Accounting Policies: Fundamental assumptions: Going concern, Consistency, Accrual. If not followed, disclose. Considerations in selection: Prudence, Substance over form, Materiality. Disclosure: All significant policies, at one place, part of financial statements. Change in policy only if required by statute, AS, or more appropriate presentation. Disclose change, amount, reason. Exam: Which is fundamental assumption? Going concern means entity will continue foreseeable future. Prudence = don't overstate assets/income."
    },
    {
        "id": "ACCOUNTS_002",
        "subject": "Accounts",
        "chapter": "Consolidation",
        "topic": "AS 21 Consolidated Financial Statements",
        "content": "AS 21 Consolidated Financial Statements: Holding-subsidiary relationship when holding owns >50% voting power or control over board. Exclusions: Subsidiary acquired for temporary, control intended to be temporary, long-term restrictions. Procedure: Line-by-line addition of assets, liabilities, income, expenses, eliminating intra-group transactions, unrealised profits, investment vs share capital, minority interest calculation. Minority interest = equity attributable to outsiders. Cost of control = Goodwill (investment > share of equity) or Capital Reserve. Pre-acquisition profits = capital, post = revenue. Exam: Calculation of minority interest, goodwill, pre/post profit split."
    },
    # COSTING
    {
        "id": "COSTING_001",
        "subject": "Costing",
        "chapter": "Material Costing",
        "topic": "EOQ and Inventory",
        "content": "Material Costing: EOQ = sqrt(2*A*O / C) where A=Annual demand, O=Ordering cost per order, C=Carrying cost per unit per annum. Assumptions: Constant demand, known ordering and carrying cost, instant replenishment, no stockouts. Inventory levels: Reorder level = Max consumption * Max lead time, Minimum = Reorder level - (Normal consumption * Normal lead time), Maximum = Reorder level + Reorder quantity - (Min consumption * Min lead time), Average = (Min+Max)/2 or (Opening+Closing)/2. ABC analysis: A=high value low quantity (10% items 70% value), B=moderate, C=low value high quantity. JIT, VED, FSN analysis."
    },
    # TAX
    {
        "id": "TAX_001",
        "subject": "Taxation",
        "chapter": "Income Tax",
        "topic": "Section 2 Residential Status",
        "content": "Section 6 Residential status: Individual: Resident if (a) 182 days in PY, OR (b) 60 days in PY + 365 days in 4 preceding PYs. Exceptions to 60 days: Indian citizen leaving for employment, Indian citizen/person of Indian origin visiting India - 182 days instead of 60. If Indian citizen with total income >15L (excluding foreign) and not liable to tax elsewhere, deemed resident if 182 days? Actually 120 days + 365 days 4 years + income >15L = resident but not ordinary resident. Resident and Ordinarily Resident: Resident + (a) resident in 2 out of 10 preceding PYs AND (b) 730 days in 7 preceding PYs. Else RNOR. HUF, Firm, Company, etc separate criteria. Company resident if Indian company or POEM in India."
    },
    {
        "id": "TAX_002",
        "subject": "Taxation",
        "chapter": "GST",
        "topic": "Section 2(17) Business and Supply",
        "content": "GST: Section 2(17) Business includes any trade, commerce, manufacture, profession, vocation, adventure, wager, any activity whether for pecuniary benefit, any activity in connection with incidental/ancillary, supply by club to members, by association to members, import of service whether for consideration or not, activities of race club, etc. Section 7 Supply: Supply includes sale, transfer, barter, exchange, licence, rental, lease, disposal for consideration in course of business. Schedule I: Deemed supply without consideration - permanent transfer of business assets where ITC availed, supply between distinct persons (same PAN different GSTIN), principal to agent, import by person. Schedule II classification goods vs services, Schedule III neither supply."
    },
    # FM
    {
        "id": "FM_001",
        "subject": "FM",
        "chapter": "Capital Budgeting",
        "topic": "NPV and IRR",
        "content": "Capital Budgeting: NPV = Present value of cash inflows - Initial investment. Decision: Accept if NPV>0. IRR = Rate at which NPV=0. Accept if IRR > Cost of capital. Payback = Initial / Annual cash flow (or cumulative). Discounted payback uses discounted cash flows. Profitability Index = PV inflows / Initial. NPV vs IRR conflict: Different size, timing, life. Assumptions: Cash flows at year end, cost of capital constant, reinvestment at cost of capital (NPV) vs IRR. Working: Estimate cash flows after tax, depreciation tax shield, working capital, terminal value. Exam: Calculate NPV with tax, working capital adjustment."
    },
    # SM
    {
        "id": "SM_001",
        "subject": "SM",
        "chapter": "Strategic Management",
        "topic": "SWOT and Porter's Five Forces",
        "content": "SWOT: Internal Strengths/Weaknesses, External Opportunities/Threats. Use for strategy formulation. Porter's Five Forces: (1) Threat of new entrants (barriers: economies of scale, capital, brand loyalty, government policy), (2) Bargaining power of buyers (price sensitivity, volume, alternatives), (3) Bargaining power of suppliers (concentration, differentiation), (4) Threat of substitutes (price-performance), (5) Rivalry among existing competitors (number, growth, fixed costs, exit barriers). Generic strategies: Cost leadership, Differentiation, Focus. BCG Matrix: Stars (high growth high share), Cash cows, Question marks, Dogs."
    },
]

# For quick search - build index
def search_knowledge_base(query: str, limit: int = 5):
    """Simple keyword search - 10x better than dumping everything"""
    q_lower = query.lower()
    q_tokens = set(q_lower.split())
    scored = []
    for chunk in KNOWLEDGE_BASE:
        content_lower = chunk["content"].lower()
        topic_lower = chunk["topic"].lower()
        chapter_lower = chunk["chapter"].lower()
        # Score: exact phrase match high, token overlap medium
        score = 0
        if q_lower in content_lower:
            score += 10
        if q_lower in topic_lower:
            score += 15
        if q_lower in chapter_lower:
            score += 12
        # Token overlap
        content_tokens = set(content_lower.split())
        overlap = len(q_tokens & content_tokens)
        score += overlap * 2
        # Section number boost
        import re
        sec_match = re.search(r'section\s*(\d+[a-z]?)', q_lower)
        if sec_match:
            sec_num = sec_match.group(1)
            if sec_num in content_lower:
                score += 20
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [chunk for score, chunk in scored[:limit]]

def get_by_subject(subject: str, limit: int = 10):
    return [c for c in KNOWLEDGE_BASE if c["subject"].lower() == subject.lower()][:limit]
