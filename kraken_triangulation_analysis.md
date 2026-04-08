# Kraken Triangulator Algorithm Analysis

The Kraken Triangulator application relies on a combination of classical geometric intersection methods, statistical estimation, and robust outlier rejection to determine the origin of tracked RF signals. The core mathematical logic is implemented in `triangulation.js`, taking raw MAVLink GPS coordinates and KrakenSDR Direction of Arrival (DOA) bearings.

Below is a detailed analysis of the algorithms and filtering sequence used by the application to compute the "best estimate" of the target's location.

## 1. Core Triangulation Algorithms

The application implements three distinct algorithms to calculate the target location, which can be selected dynamically.

### A. Least Squares Angle-of-Arrival (LS-AoA)
**Role in App:** This is the default and most computationally efficient solver for multi-station (N > 2) triangulation.
**Background Theory:**
When tracking a transmitter from three or more locations, the bearing lines will rarely intersect perfectly at a single point due to noise, multipath fading, and hardware inaccuracies. Instead of a single point, they form a "polygon of error."
LS-AoA finds the single point $(x, y)$ that minimizes the sum of the squared perpendicular distances from that point to all the bearing lines.

**Mathematical Implementation:**
1. **Flat-Earth Projection:** The algorithm first converts all WGS-84 (Lat/Lon) coordinates to a local Cartesian ENU (East, North, Up) metric grid to avoid expensive spherical trigonometry. The projection origin is the centroid of all the receiver locations.
2. **Line Equations:** Each bearing is converted into a standard 2D line equation: $a_i x + b_i y = c_i$, where $a_i = \sin(\theta)$ and $b_i = -\cos(\theta)$, and $\theta$ is the bearing angle converted to math-standard counter-clockwise rotation from East.
3. **Normal Equations:** The system builds the matrices for Weighted Least Squares: $(A^T W A)x = A^T W b$. The weights $W$ correspond to the confidence in each specific bearing.
4. **Cramer's Rule:** Because the problem reduces to a 2x2 matrix, the application solves it instantly using Cramer's rule to find the optimum Easting ($x$) and Northing ($y$), which are then converted back to Lat/Lon.

### B. Bayesian Spatial Grid Triangulation
**Role in App:** Used to generate a probabilisitic heatmap for the Leaflet UI and gracefully handle severe multipath environments where classical LS-AoA might act erratically.
**Background Theory:**
Instead of solving a geometric intersection, Bayesian Grid methods assume the target is *somewhere* and assigns a probability to every possible location on Earth based on the sensor data.

**Mathematical Implementation:**
1. **Grid Generation:** The algorithm generates a $15 \text{ km} \times 15 \text{ km}$ grid with $100\text{m}$ resolution around the initial LS-AoA estimate (to save processing power by not searching the entire globe).
2. **Gaussian Noise Modeling:** It assumes the KrakenSDR bearings have a normal (Gaussian) error distribution with a standard deviation ($\sigma$) of 5 degrees.
3. **Log-Probability Map:** For every single $100\text{m}$ grid cell, the algorithm calculates the theoretical angle from the drone to that cell. It calculates how far off that theoretical angle is from the *actual* measured bearing. It then sums the Log-Probability scores from all stations (multiplying probabilities becomes addition in log-space).
4. **Heatmap Output:** It outputs the highest scoring cell as the target coordinate and normalizes the scores to generate the visual "hot cloud" on the map, filtering out any cell with $<10\%$ probability to save frontend rendering CPU.

### C. Midpoint Ray Intersection
**Role in App:** A fallback algorithm used strictly when exactly two bearing observations are provided.
**Background Theory & Math:**
For precisely two non-parallel lines, there is exactly one intersection point. This is implemented via standard 2D vector cross-product geometry rather than Least Squares to guarantee a fast, exact geometrical intersection.

---

## 2. Signal Pre-Processing & Filtering Pipeline

Raw RF data is highly susceptible to reflections (multipath) and noise. Before `triangulation.js` passes bearings to the solvers above, it pushes the data through a rigorous filtering pipeline (`filterStations()`).

### A. Spatial Area Geofencing (AABB Raycasting)
- **Concept:** Only consider bearings that point toward a user-defined localized search area.
- **Math:** It uses 2D Axis-Aligned Bounding Box (AABB) ray-intersection math (commonly used in 3D computer graphics engines) to discard any bearing vector (ray) that doesn't physically pass through the search rectangle.

### B. Angular Separation Gating
- **Concept:** Prevent ill-conditioned matrices in the LS-AoA solver.
- **Math:** If the drone takes two bearings that are almost identical (e.g., $< 2^\circ$ difference), the lines are nearly parallel. Parallel lines cause the matrix determinant in LS-AoA to approach zero, causing massive mathematical errors. The algorithm strips out colinear redundant bearings.

### C. Spatial Outlier Rejection (Median Clustering)
- **Concept:** Remove "wild" bearings generated by heavy multipath reflections bouncing off buildings or mountains.
- **Math:** 
  1. Computes the geometric intersection of *every possible pair* of bearings.
  2. Finds the spatial median (the median X and median Y) of all those intersection points to establish the "true" cluster center.
  3. Evaluates every bearing line's perpendicular distance from the median cluster.
  4. Rejects any bearing line that "misses" the core cluster by more than $200\text{m}$.
