### User
Which 5 recipes with tomato have the fewest steps?

### Bot
Fewest estimated steps:
 1. ar:/0wx00RefE0VHzlff/GBszObKmj63Pi  Tomato Basil Smoothie  [1 steps by primary rule; 1 by sentence count]
 2. ar:3yxgq0iAqrlm2lHnLoxwJ8vQTHCd/Cm  Mediterranean Zucchini and Chickpea Salad  [1 steps by primary rule; 1 by sentence count]
 3. ar:5s.4S6mTsQWRNXHDFGWe6ea03Oac48C  Momma's Marinara Sauce  [1 steps by primary rule; 1 by sentence count]
 4. ar:9T2HkniyS.3VZB9NmFvzrfA39fMSt..  Black Bean and White Corn Salad  [1 steps by primary rule; 1 by sentence count]
 5. ar:BqfGsVgk7WHPebuzDH3IIRDAo0Vy8Hy  Refreshing Mango Chutney  [1 steps by primary rule; 1 by sentence count]

--- RECEIPT ---
tool: stats.rank_steps
filters: contains ALL of: tomato
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
analyzed: 14,820
formula: sort by estimated steps asc, then id ascending; top 5
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic; 'tomato' excludes items with: dried, juice, ketchup, paste, powder, puree...
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
ties: 58 analyzed recipes have 1 estimated steps (the boundary value); ties broken by id ascending
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:/0wx00RefE0VHzlff/GBszObKmj63Pi, ar:3yxgq0iAqrlm2lHnLoxwJ8vQTHCd/Cm, ar:5s.4S6mTsQWRNXHDFGWe6ea03Oac48C, ar:9T2HkniyS.3VZB9NmFvzrfA39fMSt.., ar:BqfGsVgk7WHPebuzDH3IIRDAo0Vy8Hy
sql: SELECT id FROM recipes WHERE is_valid=1
sql: SELECT i.recipe_id, i.canon, i.forms, i.alts FROM ingredients i JOIN recipes r ON r.id=i.recipe_id WHERE r.is_valid=1 AND i.canon LIKE '%tomato%' -- then form-aware match in Python
sql: SELECT r.id, r.title, r.n_steps, r.n_steps_alt FROM recipes r JOIN _ids ON _ids.id=r.id ORDER BY r.n_steps ASC, r.id ASC LIMIT 5

_state: dish: - | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: - | last_results: 5_