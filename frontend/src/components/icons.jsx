// Shared hand-drawn inline-SVG icon set -- no icon library, matches the app's one
// typographic signature (see index.css) with simple single-stroke line marks instead.
// Originally lived only in Home.jsx's process strip; pulled out here so Dashboard.jsx
// and ColdEmail.jsx can reuse the same visual language for their stat strips.

export const ICON_PROPS = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };

export const SearchIcon = () => (
  <svg {...ICON_PROPS}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.5-4.5" /></svg>
);
export const FilterIcon = () => (
  <svg {...ICON_PROPS}><path d="M4 5h16M7 12h10M10.5 19h3" /></svg>
);
export const SwipeIcon = () => (
  <svg {...ICON_PROPS}><rect x="6" y="4" width="12" height="16" rx="2" /><path d="M2 12h3M19 12h3M4 9l-2 3 2 3M20 9l2 3-2 3" /></svg>
);
export const TailorIcon = () => (
  <svg {...ICON_PROPS}><path d="M4 20l1-4 11-11 3 3-11 11-4 1z" /><path d="M13 6l3 3" /></svg>
);
export const ApplyIcon = () => (
  <svg {...ICON_PROPS}><path d="M21 3L11 13" /><path d="M21 3l-7 18-4-8-8-4 19-6z" /></svg>
);
export const InboxIcon = () => (
  <svg {...ICON_PROPS}><path d="M4 12h4l2 3h4l2-3h4" /><path d="M5.5 5h13l1.5 7v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6z" /></svg>
);
export const CheckCircleIcon = () => (
  <svg {...ICON_PROPS}><circle cx="12" cy="12" r="8.5" /><path d="M8.5 12.5l2.5 2.5 5-5.5" /></svg>
);
export const MailIcon = () => (
  <svg {...ICON_PROPS}><rect x="3" y="5.5" width="18" height="13" rx="1.5" /><path d="M4 6.5l8 6.5 8-6.5" /></svg>
);
export const RunsIcon = () => (
  <svg {...ICON_PROPS}><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5.5l3.5 2" /></svg>
);
