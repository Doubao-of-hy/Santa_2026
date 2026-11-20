# Certificates from projecting the rooted target count

These certificates raise the 44e63d2 reference lower bound from 36,768 to **36,778** on their own. Combine any parallel certificates by taking the maximum bound for each puzzle. The ten claims were independently re-derived by verify.py, which uses Python standard library arithmetic and never calls the search implementation.

| Puzzle | Previous lower bound | New bound | Missing targets M | Granted prefix k | Tested remaining h | Counted targets | Upper bound on hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0037 | 40 | 41 | 30 | 3 | 7 | 29 | 28 |
| 0117 | 41 | 42 | 31 | 3 | 7 | 29 | 28 |
| 0133 | 42 | 43 | 32 | 3 | 7 | 31 | 28 |
| 0170 | 41 | 42 | 32 | 2 | 7 | 31 | 28 |
| 0328 | 42 | 43 | 32 | 3 | 7 | 31 | 29 |
| 0494 | 42 | 43 | 32 | 3 | 7 | 29 | 28 |
| 0505 | 37 | 38 | 28 | 3 | 6 | 24 | 22 |
| 0595 | 37 | 38 | 28 | 3 | 6 | 23 | 22 |
| 0603 | 41 | 42 | 32 | 2 | 7 | 30 | 29 |
| 0820 | 40 | 41 | 30 | 3 | 7 | 29 | 28 |

## Argument

Grant E, the entire relaxed envelope that contains every value available by the kth distinct nontarget helper. Grant every official target as a possible operand as well, even those omitted from the count. The verifier also checks directly that at least one target lies outside the preceding envelope. This proves that every complete program needs at least k distinct helpers. Duplicate executions and physical register limits can only increase program cost.

Let S contain selected targets that cannot appear for the first time from two values in the full granted set B = E ∪ all targets. Their first appearances must use an ungranted helper. For a fixed helper x, define I(x) by connecting the counted outputs that can produce each other using x. Any component with no entry from B outside that helper’s counted neighborhood and no entry using x twice must have at least one first value made by another recipe. Subtract one from the number of vertices for each such component. This bounds the number of first appearances assigned to x with a base operand, or with x itself. Exact addition, subtraction, multiplication and division are reversible on positive integers, so the component relations are symmetric. Omitted targets may supply entries into these components.

For distinct helpers x,y, one unordered pair covers at most one target plus a bonus b(x,y) equal to max(0, number of outputs in S minus one). The verifier enumerates all pairs with two distinct outputs by solving the six pairs of arithmetic operation laws in both target orders, then checks the solutions by exact evaluation. Let D(x) sum the bonuses incident to x. With at most h extra helpers, set n = h(h−1)/2. Let U be the sum of the h largest I values, D the sum of the h largest degrees, P the sum of the n largest bonuses and J the sum of the h largest values of 2I(x)+D(x). Then the number of distinct hits is at most

    n + min(U + min(P, floor(D/2)), floor(J/2)).

The first expression bounds unary hits and bonus hits separately. The joint expression uses the same h helpers for both and counts every selected pair bonus at both endpoints. Fewer available pairs or duplicated target hits make the upper bound more generous. When the result is less than |S|, at least h+1 additional helpers are necessary. There are M distinct noninitial goal values, so at least M+k+h+1 physical arithmetic instructions are necessary.

## Hand checks

For 0117 the exact verifier reconstructs 2,101 envelope values after three helpers. It leaves 31 targets unsupported in the complete operand bank. Omitting just 5,116,519,184 and 8,495,469,166 from the count gives 29. Seven extra helpers give n=21, U=7, D=7, P=21 and J=14. Thus 21 + min(7 + min(21,3),7) = 28. The 29th target cannot fit and the total needs at least 31+3+8 = 42 steps.

A positive tiny fixture starts at 5, has cap 7, and needs 3 and 7. After the first helper, even granting target 7 as an operand, target 3 remains unsupported without another helper. The lower bound is 4. The four instructions 1=5/5, 2=1+1, 3=1+2 and 7=5+2 attain it.

A negative fixture starts at 2, has cap 8, and needs 4 and 8. If only target 8 is counted, target 4 must still be usable to produce 8. Otherwise it would appear that a nontarget helper is needed. The two instructions 4=2+2 and 8=4+4 complete the instance with zero such helpers.

## Selection and verification

The first screen considered 220 rows with at least twenty targets whose recorded domain lower bound equaled the already published floor. At the recorded prefix depth, 142 were eliminated by counting alone. Reconstructing exact envelopes ruled out a further 46 rows. The remaining 32 rows needed at most three omitted goals. Search evaluated 18,045 subsets and stopped each winning row once it found a strict witness.

Set SANTA_CHECKOUT to the Git repository containing 44e63d2, then run the following commands. No solver packages or public programs are required by either verification script. The official puzzle file is needed only for the actual competition witnesses.

    python small_check.py
    python verify.py --puzzles PATH/TO/puzzles.csv

verified.json gives each increment, omitted integers, actual envelope size, helper budget and the five arithmetic terms of the hit ceiling. witnesses.json is the minimal input to the verifier. small-check.json records the exhaustive breadth-first check, direct enumeration of all possible pairs and its two hand-check fixtures. The small test covered 6,212 seed/target instances with value limit at most 8, testing 11,478 subset/helper budgets against true optima.

## All 1,000 puzzles

The subsequent frozen screen checked all 1,000 rows and depths 0 through 4 with the existing 3,500-value cap. Twenty rows were already tight, and the initial count ceiling ruled out 231 further rows at every depth. The remaining 749 underwent the applicable depth checks. Six further rows increased, bringing the method-only total to 36,778. full-design.json records the extension, full-results.json.gz the individual outcomes, and screening.json the aggregate coverage. The cap excluded 1,008 depth checks. Some rows can have several excluded depths.

The only unresolved four-deletion case after the first extension was 0270. Its 26 unsupported targets produce 14,950 ways to delete four. Every one left capacity at least 22 for 22 selected targets, so none yielded a proof. On all ten successful rows the enhanced floor and the admissible envelope screen ruled out a second gain at the checked depths. These bounds are specific to the registered finite envelope and subset search.

For a complete search reproduction from the repository environment, run search.py, full.py, closeout.py and verify.py in this directory. The competition proof itself can be verified with only verify.py, design.json, witnesses.json, the frozen Git lower-bound table and official puzzles.csv. File claims.csv is a compact per-row import.
