# DAR-673: checked-answer matcher on the FAQ test pairs

Written by `python -m evaluation.faq.run --write`. Bar (ticket): rewordings served from their own entry at least 25/30, similar-but-different questions served 0/30.

## pairs.json: written with the matcher (tuning)

| threshold | rewordings served (own entry) | served the wrong entry | different served | different served, similarity alone |
|---|---|---|---|---|
| 0.90 | 29/30 | 0 | 8/30 | 22/30 |
| 0.92 | 28/30 | 0 | 5/30 | 19/30 |
| 0.93 | 28/30 | 0 | 2/30 | 16/30 |
| 0.94 | 28/30 | 0 | 1/30 | 14/30 |
| 0.95 **(set)** | 24/30 | 0 | 0/30 | 13/30 |
| 0.96 | 21/30 | 0 | 0/30 | 8/30 |
| 0.97 | 17/30 | 0 | 0/30 | 6/30 |
| 0.98 | 11/30 | 0 | 0/30 | 3/30 |

At 0.95, rewordings not served:

- wztc-01 (similarity 0.945): For a road posted at 55 miles per hour, how long does a lane closure taper have to be at minimum?
- wztc-04 (number/unit or contrast word differs): On an interstate, how narrow can a lane be in a work zone?
- utilities-03 (similarity 0.95): How much cover is required at minimum for fiber optic cable in the right of way?
- utilities-09 (similarity 0.909): How high must overhead power lines be above a highway at minimum?
- tmsd-05 (similarity 0.95): How high above the roadway must a traffic signal head be mounted at minimum?
- tmsd-10 (similarity 0.948): How far apart do driveways have to be at minimum on a major thoroughfare?

At 0.95, similar-but-different questions and what stopped them (rule = numbers/units or contrast words; division = asked of another division):

| faq | kind | similarity to stored | stopped by | served |
|---|---|---|---|---|
| wztc-01 | number | 0.951 | rule | no |
| wztc-02 | material | 0.846 | threshold | no |
| wztc-03 | division |  | division | no |
| wztc-04 | material | 0.900 | threshold | no |
| wztc-05 | unit | 0.975 | rule | no |
| wztc-06 | unit | 0.974 | rule | no |
| wztc-07 | material | 0.937 | threshold | no |
| wztc-08 | material | 0.927 | threshold | no |
| wztc-09 | division |  | division | no |
| wztc-10 | material | 0.956 | rule | no |
| utilities-01 | material | 0.925 | threshold | no |
| utilities-02 | material | 0.924 | threshold | no |
| utilities-03 | material | 0.908 | threshold | no |
| utilities-04 | material | 0.990 | rule | no |
| utilities-05 | material | 0.904 | threshold | no |
| utilities-06 | material | 0.947 | threshold | no |
| utilities-07 | division |  | division | no |
| utilities-08 | material | 0.870 | threshold | no |
| utilities-09 | number | 0.956 | rule | no |
| utilities-10 | material | 0.988 | rule | no |
| tmsd-01 | number | 0.935 | rule | no |
| tmsd-02 | material | 0.827 | threshold | no |
| tmsd-03 | unit | 0.993 | rule | no |
| tmsd-04 | material | 0.953 | rule | no |
| tmsd-05 | material | 0.973 | rule | no |
| tmsd-06 | number | 0.952 | rule | no |
| tmsd-07 | division |  | division | no |
| tmsd-08 | division |  | division | no |
| tmsd-09 | number | 0.962 | rule | no |
| tmsd-10 | unit | 0.964 | rule | no |

## pairs_holdout.json: written without seeing the matcher (held out)

| threshold | rewordings served (own entry) | served the wrong entry | different served | different served, similarity alone |
|---|---|---|---|---|
| 0.90 | 19/30 | 0 | 6/30 | 24/30 |
| 0.92 | 16/30 | 0 | 5/30 | 23/30 |
| 0.93 | 15/30 | 0 | 4/30 | 22/30 |
| 0.94 | 10/30 | 0 | 3/30 | 19/30 |
| 0.95 **(set)** | 8/30 | 0 | 0/30 | 14/30 |
| 0.96 | 4/30 | 0 | 0/30 | 9/30 |
| 0.97 | 3/30 | 0 | 0/30 | 8/30 |
| 0.98 | 1/30 | 0 | 0/30 | 5/30 |

At 0.95, rewordings not served:

- wztc-01 (similarity 0.938): On a road with 12-foot lanes and a 55 miles per hour speed limit, how long should the merging taper be for a lane closure?
- wztc-03 (similarity 0.939): For a work zone posted at 60 miles per hour, how long does the buffer space have to be at minimum?
- wztc-04 (number/unit or contrast word differs): During the day, what kind of high-vis safety apparel is required for flaggers?
- wztc-05 (similarity 0.819): For a moving operation on a freeway, does the shadow truck need a TMA?
- wztc-06 (similarity 0.913): What's the shortest a downstream taper is allowed to be?
- wztc-07 (similarity 0.749): On a significant project, who has to prepare the TMP?
- wztc-08 (number/unit or contrast word differs): Is it OK to leave a two-inch drop-off at the edge of pavement beside an open lane overnight?
- wztc-09 (similarity 0.943): In feet, what's the length of a single NC portable concrete barrier segment?
- utilities-01 (similarity 0.896): When a utility is bored and jacked beneath the pavement, how much cover is required at minimum?
- utilities-02 (number/unit or contrast word differs): What's required when a utility job blocks a sidewalk for seven or more working days?
- utilities-04 (number/unit or contrast word differs): On a road without curb posted at 45 miles per hour, what setback from the edge of the travel lane is required for a new utility pole?
- utilities-05 (number/unit or contrast word differs): Where an overhead electric line crosses a state highway, how high above the road does it have to be at minimum?
- utilities-06 (similarity 0.918): Are longitudinal utility installations allowed within the controlled access limits of an interstate?
- utilities-08 (similarity 0.909): If a utility crew is working 3 ft off the edge of the travel lane, do they need to close the lane?
- utilities-09 (similarity 0.946): When a utility closes a road, who covers the cost of the detour?
- utilities-10 (similarity 0.719): What work does SUE quality level B include?
- tmsd-01 (number/unit or contrast word differs): What's the maximum number of TODS sign panels allowed on a single approach to an intersection?
- tmsd-02 (similarity 0.887): For a signalized approach posted at 45 miles per hour, how long should the yellow be?
- tmsd-05 (similarity 0.923): At an unsignalized intersection, what conditions justify adding a left-turn lane?
- tmsd-06 (similarity 0.934): What's the deadline for a regional office to finish investigating a fatal crash?
- tmsd-09 (similarity 0.931): When a new sidewalk is built along a state highway within municipal limits, who is responsible for maintaining it?
- tmsd-10 (similarity 0.936): When timing the pedestrian clearance interval at a signal, what walking speed should be assumed?

At 0.95, similar-but-different questions and what stopped them (rule = numbers/units or contrast words; division = asked of another division):

| faq | kind | similarity to stored | stopped by | served |
|---|---|---|---|---|
| wztc-01 | number | 0.955 | rule | no |
| wztc-02 | material | 0.934 | threshold | no |
| wztc-03 | unit | 0.984 | rule | no |
| wztc-04 | material | 0.970 | rule | no |
| wztc-05 | material | 0.940 | threshold | no |
| wztc-06 | material | 0.954 | rule | no |
| wztc-07 | division |  | division | no |
| wztc-08 | number | 0.960 | rule | no |
| wztc-09 | unit | 0.939 | rule | no |
| wztc-10 | division |  | division | no |
| utilities-01 | material | 0.909 | threshold | no |
| utilities-02 | number | 0.944 | rule | no |
| utilities-03 | material | 0.986 | rule | no |
| utilities-04 | number | 0.951 | rule | no |
| utilities-05 | material | 0.921 | threshold | no |
| utilities-06 | material | 0.979 | rule | no |
| utilities-07 | unit | 0.976 | rule | no |
| utilities-08 | unit | 0.990 | rule | no |
| utilities-09 | division |  | division | no |
| utilities-10 | material | 0.949 | threshold | no |
| tmsd-01 | division |  | division | no |
| tmsd-02 | number | 0.945 | rule | no |
| tmsd-03 | unit | 0.988 | rule | no |
| tmsd-04 | number | 0.939 | rule | no |
| tmsd-05 | material | 0.952 | rule | no |
| tmsd-06 | division |  | division | no |
| tmsd-07 | material | 0.821 | threshold | no |
| tmsd-08 | material | 0.996 | rule | no |
| tmsd-09 | material | 0.971 | rule | no |
| tmsd-10 | material | 0.941 | threshold | no |

