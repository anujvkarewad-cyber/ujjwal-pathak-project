"""
Auto-generated KB - MIGRATED TO MONGODB
3494 chunks now in Atlas (knowledge_chunks collection)
This file is fallback only (16 manual chunks), MongoDB is primary for smooth search
v5.5 MongoDB RAG LIVE
"""
KNOWLEDGE_BASE_AUTO = [
  {
    "id": "COSTING_001",
    "subject": "Costing",
    "chapter": "Material Costing",
    "topic": "EOQ and Inventory",
    "content": "Material Costing: EOQ = sqrt(2*A*O / C) where A=Annual demand, O=Ordering cost per order, C=Carrying cost per unit per annum. Assumptions: Constant demand, known ordering and carrying cost, instant replenishment, no stockouts. Inventory levels: Reorder level = Max consumption * Max lead time, Minimum = Reorder level - (Normal consumption * Normal lead time), Maximum = Reorder level + Reorder quantity - (Min consumption * Min lead time), Average = (Min+Max)/2 or (Opening+Closing)/2. ABC analysis: A=high value low quantity (10% items 70% value), B=moderate, C=low value high quantity. JIT, VED, FSN analysis."
  },
  {
    "id": "LAW_SEC43_001",
    "subject": "Law",
    "chapter": "Share Capital and Debentures",
    "topic": "Section 43 - Kinds of Share Capital",
    "content": "Section 43 of Companies Act, 2013 deals with Kinds of Share Capital. Equity Share Capital - With voting rights, or with differential rights as to dividend, voting, etc. All share capital which is NOT preference share capital. Preference Share Capital - Carries preferential right on dividend (fixed amount/rate) and repayment of capital on winding up. Has priority over equity. For private companies, memorandum or articles may permit other kinds. DVR conditions - Rule 4: 26% voting power limit, 3 years distributable profits track record, no default in filing annual accounts/returns."
  }
]
# Total: 2 fallback chunks, primary is 3494 in MongoDB Atlas
