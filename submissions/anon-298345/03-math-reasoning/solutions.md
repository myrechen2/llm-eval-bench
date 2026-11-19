# Task 03: Math Reasoning Solutions

## 1
By AM-GM on the 6 positive terms $x, \frac{y}{2}, \frac{y}{2}, \frac{z}{3}, \frac{z}{3}, \frac{z}{3}$ summing to $6$:
$$1 = \frac{x + 2(y/2) + 3(z/3)}{6} \ge \left(\frac{x y^2 z^3}{2^2 \cdot 3^3}\right)^{1/6} = \left(\frac{x y^2 z^3}{108}\right)^{1/6}.$$
Equality holds at $(x, y, z) = (1, 2, 3)$, giving maximum **108**.

## 2
Let $S_n(x) = \sum_{\text{valid len } n} x^{\sum d_i}$. For $x=1$, $S_{10}(1) = 4 \cdot 3^9 = 78732$.
For $\zeta \ne 1$ with $\zeta^5 = 1$, the transfer matrix is $M = D(J - I)$ where $D = \operatorname{diag}(1, \zeta, \zeta^2, \zeta^3)$. Its characteristic polynomial satisfies $M^4 - \zeta^3 M^2 + 2\zeta^2 M - 3\zeta I = 0$, so $S_{n+4} = \zeta^3 S_{n+2} - 2\zeta^2 S_{n+1} + 3\zeta S_n$.
Writing $S_n(\zeta) = c_n \zeta^{-n}$ gives the integer recurrence $c_{n+4} = c_{n+2} - 2 c_{n+1} + 3 c_n$ with $(c_1, c_2, c_3, c_4) = (-1, 2, -4, 8)$.
Computing forward: $c_5 = -11, c_6 = 22, c_7 = -39, c_8 = 68, c_9 = -116, c_{10} = 212$.
Since $\zeta^{-10} = 1$, $S_{10}(\zeta) = 212$ for all 4 non-trivial 5th roots of unity.
By roots of unity filter, the count is $\frac{78732 + 4 \cdot 212}{5} = \frac{79580}{5} = \mathbf{15916}$.

## 3
$f^3 = f$ holds iff $f|_A$ is an involution on $A = f(S)$ and $f(S \setminus A) \subseteq A$.
With $I(k)$ denoting the number of involutions on $k$ elements ($I(1..7) = 1, 2, 4, 10, 26, 76, 232$), the count is:
$$\sum_{k=1}^7 \binom{7}{k} I(k) k^{7-k} = 7 + 1344 + 11340 + 22400 + 13650 + 3192 + 232 = \mathbf{52165}.$$

## 4
For $0 \le n < 2^{20}$, let $E$ and $O$ be the number of 1-bits at the 10 even and 10 odd positions. Since $2^k \equiv (-1)^k \pmod 3$, we need $E - O \equiv 0 \pmod 3$ and $E + O \equiv 0 \pmod 3$, which is equivalent to $E \equiv 0 \pmod 3$ and $O \equiv 0 \pmod 3$.
The number of ways for each half is $\binom{10}{0} + \binom{10}{3} + \binom{10}{6} + \binom{10}{9} = 341$.
Excluding $n = 0$ (and $2^{20}$ has popcount 1), the answer is $341^2 - 1 = 116281 - 1 = \mathbf{116280}$.

## 5
By Vieta jumping, $\frac{a^2 + b^2}{ab + 1} = m^2$ for some integer $m \ge 1$.
For $m = 1$, $(1, 1)$ is the unique positive solution.
For $m \ge 2$, positive solutions with $a < b$ are adjacent terms $(x_n, x_{n+1})$ of $x_0 = 0, x_1 = m, x_{n+1} = m^2 x_n - x_{n-1}$:
- $m = 2$: $(2,8), (8,30), (30,112), (112,418)$ (4 pairs);
- $m = 3$: $(3,27), (27,240)$ (2 pairs);
- $4 \le m \le 10$: $(m, m^3)$ (7 pairs).
Counting both orders for $a \ne b$ plus $(1,1)$ gives $2(4 + 2 + 7) + 1 = \mathbf{27}$.

## 6
Using column-by-column profile DP on $3 \times n$ with $1 \times 2$ dominoes and $2 \times 2$ squares, the reachable states are empty (`0`), top/bottom 1-cell (`1`/`4`), top/bottom 2-cell (`3`/`6`), and full (`7`).
For even $n$, let $a_n$ be ways to reach `0` and $c_n$ be ways to reach `6` (same as `3`). Then $a_{n+2} = 5a_n + 2c_n$ and $c_{n+2} = 2a_n + 2c_n$ with $(a_0, c_0) = (1, 0)$.
This gives $a_2 = 5, a_4 = 29, a_6 = 173, a_8 = 1037, a_{10} = 6221, a_{12} = \mathbf{37325}$.

## 7
By law of cosines, $\cos A = \frac{15^2 + 7^2 - 13^2}{2 \cdot 15 \cdot 7} = \frac{105}{210} = \frac{1}{2}$, so $\angle A = 60^\circ$.
Placing $A = (0, 0)$, $C = (15, 0)$, $B = (\frac{7}{2}, \frac{7\sqrt{3}}{2})$:
- $H = (\frac{7}{2}, \frac{23\sqrt{3}}{6})$
- $O = (\frac{15}{2}, -\frac{\sqrt{3}}{6})$
- $I = (\frac{9}{2}, \frac{3\sqrt{3}}{2})$
Then $\vec{OI} = (-3, \frac{5\sqrt{3}}{3})$ and $\vec{OH} = (-4, 4\sqrt{3})$, so $[OIH] = \frac{1}{2} |(-3)(4\sqrt{3}) - (-4)(\frac{5\sqrt{3}}{3})| = \frac{8\sqrt{3}}{3}$.
Thus $m + n = 8 + 3 = \mathbf{11}$.

## 8
Let $A_n(x)$ be the rook polynomial of the tridiagonal forbidden board $|i - j| \le 1$ on $n \times n$, and $P_n(x)$ be the rook polynomial with column $n$ removed.
They satisfy $P_n(x) = A_{n-1}(x) + x P_{n-1}(x)$ and $A_n(x) = (1+x)A_{n-1}(x) + 2x P_{n-1}(x) + x^2 A_{n-2}(x)$ with $A_0=1, A_1=1+x, P_1=1$.
Computing up to $n = 9$ gives:
$A_9(x) = 1 + 25x + 254x^2 + 1356x^3 + 4115x^4 + 7191x^5 + 7018x^6 + 3538x^7 + 789x^8 + 55x^9$.
By inclusion-exclusion, $\sum_{k=0}^9 (-1)^k r_k (9-k)! = \mathbf{15702}$.
