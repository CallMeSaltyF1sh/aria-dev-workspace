# Dev Workspace design system

Dev Workspace is a desktop research workbench for reviewing Aria recordings, labeling dressing phases, running VLM tasks, and comparing predictions with human annotations. The concept screens use fictional samples.

## Visual direction

Borrow the high contrast typography, neutral surfaces, compact navigation, and restrained controls from the [Vercel Dashboard](https://vercel.com/changelog/dashboard-navigation-redesign-rollout) and [Geist](https://vercel.com/geist/introduction). Dev Workspace has its own sidebar, video workspace, timeline, and evaluation layouts.

- Use a near white canvas (#FAFAFA), white panels, 1px borders (#E6E6E6), and charcoal text and primary controls (#171717). Use 6px radii for controls and 8px for panels.
- Use Geist for text and Geist Mono for timestamps, file paths, and technical values. Keep labels and table values legible at desktop density.
- Use blue for focus and progress, green for successful states, amber for warnings, and red for errors or destructive actions. Show status labels and phase IDs alongside color.
- Keep the video surface dark to distinguish media from surrounding controls. Show phases P0 through P4 on the timeline in gray, amber, orange, blue, and mint respectively.
- Use Tabler outline icons from the collection listed in Iconstack. The data scan icon is 16px and the row chevron is 18px. Keep the larger click target around the row chevron.

## Screens

The sidebar links to Data Library, Prompt Library, VLM Tasks, and Evaluation. Video detail has a page-level tab bar. Only Video & Annotation shows the player and annotation editor. The annotation axis uses 0.1-second split-point steps, time bubbles, phase selection, a phase legend, and Save. The delete confirmation shows which local files will be removed. Keep explanatory copy near actions only when it helps someone decide or recover from an error.
