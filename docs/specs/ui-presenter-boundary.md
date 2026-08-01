# UI Presenter Boundary Contract

- `UI-PRES-01`: Pure presenter functions MUST translate normalized runtime
  values into immutable view data without importing or touching Tk widgets.
- `UI-PRES-02`: Tk renderers MUST consume presenter output on the UI owner thread
  and MUST NOT reproduce core calculation or access-policy logic.
- `UI-PRES-03`: Worker callbacks MUST cross the dispatcher before mutating a
  widget, opening a dialog, or changing window geometry.
- `UI-PRES-04`: Disabled public features MUST have no renderer lifecycle and no
  hidden placeholder that implies subscriber functionality is locally present.
- `UI-PRES-05`: Compact and high-DPI layouts MUST keep the timer and enabled
  public controls reachable without overlapping fixed window controls.

Subscriber UI is attached through the optional Strike Prediction interface in
the private assembly. Its implementation and presentation tests are not part of
this public contract.
