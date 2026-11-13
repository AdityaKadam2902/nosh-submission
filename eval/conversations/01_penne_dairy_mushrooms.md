### User
Find penne pasta

### Bot
300 recipes passed all filters (of 300 retrieved candidates); showing 10:
 1. ar:hzvAPQudIHjif5vLsP8vv.H8aTThvAq  Bacon and Parmesan Penne Pasta  [3 steps, 5 ingredients]
 2. ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ.  Penne Pasta with Spinach and Bacon  [3 steps, 6 ingredients]
 3. ar:Ds7VCz2ZVAvWeI/YBnNcA/lzUZGjb7G  Tuna Alfredo with Penne Pasta  [2 steps, 6 ingredients]
 4. ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO  Creamy Penne Pasta  [2 steps, 10 ingredients]
 5. ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om  Penne Pasta with Cannellini Beans and Escarole  [2 steps, 6 ingredients]
 6. ar:jfbKxlKg793qYyjjiDwAPlu.AOZgDZO  Portobello Penne Pasta Casserole  [4 steps, 11 ingredients]
 7. ar:GzMPrQqLIgRDdF4Nb5yxM1Cu6CxCq1W  Asparagus, Chicken and Penne Pasta  [3 steps, 9 ingredients]
 8. ar:O/vIRg8lYa0cKmTwTWHZwOFMj4.cwmG  Penne Pesto Pasta Salad  [2 steps, 7 ingredients]
 9. ar:1y7j2vPKV2KEQbMJ7GgJw1Z5X/yKF/S  Penne Pasta with Veggies  [5 steps, 11 ingredients]
10. fn:4tITdgG7jS.lgVlCCxBlTiiLq9JCj2G  Creamy Ham and Penne Pasta  [2 steps, 6 ingredients]

--- RECEIPT ---
tool: search
filters: text query: 'penne pasta'
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
retrieval: FTS5 BM25 (title weight 5x), query mode AND, top 300; vector index not built -> BM25 only
ordering: BM25 score ascending (best first), ties by id
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
candidates: 300
dropped by filters: none
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:hzvAPQudIHjif5vLsP8vv.H8aTThvAq, ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ., ar:Ds7VCz2ZVAvWeI/YBnNcA/lzUZGjb7G, ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO, ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om, ar:jfbKxlKg793qYyjjiDwAPlu.AOZgDZO, ar:GzMPrQqLIgRDdF4Nb5yxM1Cu6CxCq1W, ar:O/vIRg8lYa0cKmTwTWHZwOFMj4.cwmG, ar:1y7j2vPKV2KEQbMJ7GgJw1Z5X/yKF/S, fn:4tITdgG7jS.lgVlCCxBlTiiLq9JCj2G
sql: SELECT r.id, bm25(recipes_fts, 5.0, 1.0) AS score FROM recipes_fts JOIN recipes r ON r.rowid = recipes_fts.rowid WHERE recipes_fts MATCH ? ORDER BY score, r.id LIMIT ?

_state: dish: penne pasta | include: - | exclude: - | restrictions: - | max_steps: - | available: - | preferences: - | focus: - | last_results: 10_

---

### User
I cannot have dairy

### Bot
69 recipes passed all filters (of 406 retrieved candidates); showing 10:
 1. ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ.  Penne Pasta with Spinach and Bacon  [3 steps, 6 ingredients]  dairy:free
 2. ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om  Penne Pasta with Cannellini Beans and Escarole  [2 steps, 6 ingredients]  dairy:free
 3. fn:ck/foCIv1g.W0SyPMLF5DWS/ZdeQBRi  Penne Pasta Salad with Sun Dried Tomatoes, Asparagus and Basil  [2 steps, 8 ingredients]  dairy:free
 4. fn:Fa0AuDYa4SItG.bL1kA8votemAaTPZ6  Italian Sausage Penne Pasta with Tomatoes and Peas and Sweet Corn Salad  [2 steps, 12 ingredients]  dairy:free
 5. fn:3xGSq4jxwkdB1cabVkvXBRVHv7OxflC  Scallops and Penne Pasta in a Saffron Broth  [10 steps, 11 ingredients]  dairy:free
 6. ar:XYtz2e4LcminKhKShizshuMDz29MI0C  Non-Dairy Baked Penne Pasta  [7 steps, 16 ingredients]  dairy:free
 7. ar:9mPiUMSt4KndASd0tYPD7iKvkRhsO2i  Pat's Simple Penne  [4 steps, 5 ingredients]  dairy:free
 8. fn:lbdoJWX6HAMrTwmYjkFPyxu/lqR/lLO  Penne with Mushrooms and Caramelized Garlic Topped with Parsley  [5 steps, 5 ingredients]  dairy:free
 9. ar:kRoPOYpOULlZJJvfVyfZNStj4DNvQE6  Penne with Vegan Arrabbiata Sauce  [3 steps, 7 ingredients]  dairy:free
10. ar:J0i796t1eGNrEYZx/buYDaILREObz.y  Penne with Eggplant  [2 steps, 10 ingredients]  dairy:free

Uncertain (possible match for a restriction; NOT in the list above; 1 total):
  - fn:PJ.Ilz8E.ei90Y1lXVotPRJu/KBF23q  Penne al Cioccolato con Anchovies: Penne with Chocolate and Anchovies  (line 5 '2 cups/457 g chopped finest quality plain dark chocolate (at least 70 percent cocoa)' -> may_contain: 'chocolate')

--- RECEIPT ---
tool: search
filters: text query: 'penne pasta'; restrictions (3-state, 'possible' goes to Uncertain): dairy
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
retrieval: FTS5 BM25 (title weight 5x), query mode AND, top 1000; vector index not built -> BM25 only
ordering: BM25 score ascending (best first), ties by id
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
candidates: 406
dropped by filters: restriction_contains=336
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ., ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om, fn:ck/foCIv1g.W0SyPMLF5DWS/ZdeQBRi, fn:Fa0AuDYa4SItG.bL1kA8votemAaTPZ6, fn:3xGSq4jxwkdB1cabVkvXBRVHv7OxflC, ar:XYtz2e4LcminKhKShizshuMDz29MI0C, ar:9mPiUMSt4KndASd0tYPD7iKvkRhsO2i, fn:lbdoJWX6HAMrTwmYjkFPyxu/lqR/lLO, ar:kRoPOYpOULlZJJvfVyfZNStj4DNvQE6, ar:J0i796t1eGNrEYZx/buYDaILREObz.y
sql: SELECT r.id, bm25(recipes_fts, 5.0, 1.0) AS score FROM recipes_fts JOIN recipes r ON r.rowid = recipes_fts.rowid WHERE recipes_fts MATCH ? ORDER BY score, r.id LIMIT ?

_state: dish: penne pasta | include: - | exclude: - | restrictions: ['dairy'] | max_steps: - | available: - | preferences: - | focus: - | last_results: 10_

---

### User
also no mushrooms

### Bot
61 recipes passed all filters (of 406 retrieved candidates); showing 10:
 1. ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ.  Penne Pasta with Spinach and Bacon  [3 steps, 6 ingredients]  dairy:free
 2. ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om  Penne Pasta with Cannellini Beans and Escarole  [2 steps, 6 ingredients]  dairy:free
 3. fn:ck/foCIv1g.W0SyPMLF5DWS/ZdeQBRi  Penne Pasta Salad with Sun Dried Tomatoes, Asparagus and Basil  [2 steps, 8 ingredients]  dairy:free
 4. fn:Fa0AuDYa4SItG.bL1kA8votemAaTPZ6  Italian Sausage Penne Pasta with Tomatoes and Peas and Sweet Corn Salad  [2 steps, 12 ingredients]  dairy:free
 5. fn:3xGSq4jxwkdB1cabVkvXBRVHv7OxflC  Scallops and Penne Pasta in a Saffron Broth  [10 steps, 11 ingredients]  dairy:free
 6. ar:XYtz2e4LcminKhKShizshuMDz29MI0C  Non-Dairy Baked Penne Pasta  [7 steps, 16 ingredients]  dairy:free
 7. ar:9mPiUMSt4KndASd0tYPD7iKvkRhsO2i  Pat's Simple Penne  [4 steps, 5 ingredients]  dairy:free
 8. ar:kRoPOYpOULlZJJvfVyfZNStj4DNvQE6  Penne with Vegan Arrabbiata Sauce  [3 steps, 7 ingredients]  dairy:free
 9. ar:J0i796t1eGNrEYZx/buYDaILREObz.y  Penne with Eggplant  [2 steps, 10 ingredients]  dairy:free
10. ar:HKOP45CaBPW0XwN77bZjJtVFtXVDV..  Pasta and Beans  [3 steps, 6 ingredients]  dairy:free

Uncertain (possible match for a restriction; NOT in the list above; 1 total):
  - fn:PJ.Ilz8E.ei90Y1lXVotPRJu/KBF23q  Penne al Cioccolato con Anchovies: Penne with Chocolate and Anchovies  (line 5 '2 cups/457 g chopped finest quality plain dark chocolate (at least 70 percent cocoa)' -> may_contain: 'chocolate')

--- RECEIPT ---
tool: search
filters: text query: 'penne pasta'; excludes: mushroom; restrictions (3-state, 'possible' goes to Uncertain): dairy
dataset: 122,918 valid of 125,164 records (2,246 invalid, excluded)
retrieval: FTS5 BM25 (title weight 5x), query mode AND, top 1000; vector index not built -> BM25 only
ordering: BM25 score ascending (best first), ties by id
normalization: form-aware token-sequence match on normalized names (aliases, singular forms); e.g. garlic powder is not counted as garlic
step rule: estimated instruction steps: newline-separated blocks if >=2 blocks, else sentences (ADVERTISEMENT/bare numbering removed; recipebot/steps.py)
candidates: 406
dropped by filters: exclude=57, restriction_contains=287
valid = title non-blank AND >=1 clean ingredient line AND >=1 instruction step
duplicates: near-duplicate recipes (same title + ingredients, mostly across sources) are NOT removed; see docs/DATA_AUDIT.md section 4
recipe ids: ar:23to8XzUux0FF.g5ZFsqnxvhByMzfJ., ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om, fn:ck/foCIv1g.W0SyPMLF5DWS/ZdeQBRi, fn:Fa0AuDYa4SItG.bL1kA8votemAaTPZ6, fn:3xGSq4jxwkdB1cabVkvXBRVHv7OxflC, ar:XYtz2e4LcminKhKShizshuMDz29MI0C, ar:9mPiUMSt4KndASd0tYPD7iKvkRhsO2i, ar:kRoPOYpOULlZJJvfVyfZNStj4DNvQE6, ar:J0i796t1eGNrEYZx/buYDaILREObz.y, ar:HKOP45CaBPW0XwN77bZjJtVFtXVDV..
sql: SELECT r.id, bm25(recipes_fts, 5.0, 1.0) AS score FROM recipes_fts JOIN recipes r ON r.rowid = recipes_fts.rowid WHERE recipes_fts MATCH ? ORDER BY score, r.id LIMIT ?

_state: dish: penne pasta | include: - | exclude: ['mushroom'] | restrictions: ['dairy'] | max_steps: - | available: - | preferences: - | focus: - | last_results: 10_

---

### User
show the second one

### Bot
ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om  Penne Pasta with Cannellini Beans and Escarole
source ar | valid=True | 6 ingredients | 2 estimated steps
(display strips the literal 'ADVERTISEMENT' noise; the stored original is untouched)

INGREDIENTS (original -> normalized):
   0. 1 (16 ounce) package dry penne pasta  ->  penne pasta
   1. 1 head escarole, chopped  ->  escarole
   2. 1 (15.5 ounce) can cannellini beans, with liquid  ->  cannellini bean
   3. 1 (14.5 ounce) can diced tomatoes with garlic and onion, drained  ->  tomato with garlic and onion
   4. salt and ground black pepper to taste  ->  black pepper
   5.   ->  (not an ingredient)

INSTRUCTIONS:
Bring a large pot of lightly salted water to a boil, and cook the penne pasta 8 to 10 minutes or until al dente; drain.
In a skillet over medium heat, cook and stir the escarole, cannellini beans and liquid, and diced tomatoes with garlic and onion until heated through. Season with salt and pepper. Toss with the cooked pasta to serve.

_state: dish: penne pasta | include: - | exclude: ['mushroom'] | restrictions: ['dairy'] | max_steps: - | available: - | preferences: - | focus: ar:zwRAInNlhnKD1jMf/HOm5a9oKhjC8Om | last_results: 10_