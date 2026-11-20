# Reversing two shared unknown inputs, November 20

Frozen incumbent: public-assisted/submission.csv at Hansen0223/Santa_2026 revision 472b715858b74910ca9b1eafcbea4d64183fa09d, 134385 instructions, SHA-256 85f46d2d7a67afb91ec59c9b2ace8b974d7334ed8677250170aae36805561035. Lanes are public-assisted only. The incumbent row keeps its existing upstream attribution. The independent release is an additional donor, with no independent score claim.

Eligible donors, hashes of normalized programs.csv tables, in addition to the incumbent:
- Local independent submission at the same revision: f1bb3f6b2eb7f20280db2b551710aa080a09f1e0405f9cc7b13d845481ae3a5f.
- Asterios Panoras v118: 5d5afb3f812996488f1f6e83687d38e8674b9442a0514435b5c7872c0e7ac8fe.
- Hanif Noer Rofiq v23: 48f7dbc58893dc54d0d601adde202cddd8fd356bfaa6be90ed3486d1a5e7d260.
- Alex Chilton, Rudolph v67: 085eda6649d8f3b8d51d5f32e9f998c3978b5fa29ffb45e45e7e93fb322d3051.

Eligibility used only lengths and physical-program text diversity. Restrict to frozen incumbent length 100 through 320 inclusive, and at least three distinct normalized program strings among the five rows. Sort 78 eligible IDs by the hexadecimal SHA-256 of ASCII interface-elimination-v1 joined directly to the full ID scored_NNNN.
- Development, first 8: 0750, 0161, 0331, 0435, 0807, 0793, 0309, 0754.
- Held-out, next 16: 0830, 0148, 0109, 0530, 0144, 0062, 0428, 0991, 0152, 0568, 0745, 0785, 0757, 0781, 0334, 0317.

A graft of whole target cones is already implemented in crossover_graft.py. affine_islands.py synthesizes outputs forward from known atoms. Here, identify two observed arithmetic expressions depending simultaneously on the same independent pair of unknown live-in values. For nonzero determinant, solve in the reverse direction for both unknowns. Introduce paid bounded exact arithmetic for scaled endpoints, shifted endpoints, signed sums and exact divisions. Tests will record whether newly generated numbers already occur in the union of parents. Parent-only and treatment use the same donor graphs, solver and full physical replay. Check a manufactured two-input positive witness and a rank-one negative witness first. Measure gain against both the inactive control and the frozen public table. Eligible donor or stronger independent solutions that improve the control are credited separately. Preserve the incumbent for timeouts and invalid programs, with no optimality claim.

Trigger: run the development set, inspect useful distinct reverse equations, non-parent intermediates, completed physical candidates and attributable savings. Run the held-out set if the treatment improves any development row or yields usable bridge values on at least two development rows. Otherwise record the lack of coverage and stop this experiment without additional seed scans. If there are no usable bridges in development the preregistered holdout remains unused.
