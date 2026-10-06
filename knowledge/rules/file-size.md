# File size: where a long file goes

| Type | Target | Ceiling |
|---|---|---|
| Screen | 30-70 | 150 |
| Refactor body / widget | 80-120 | 150 |
| Repo | 120 | 250 |
| Model | 200 | 400 |
| Cubit / data source | no hard limit | 900 before it is suspicious |

A cubit has no ceiling because behaviour is genuinely its job. A screen has a
tight one because a screen that grew past it has absorbed work belonging to a
cubit or a widget.

## The split, in order

1. **A `_build...` method in a screen** is the first thing to move. If it renders
   a section of the body, it belongs in `presentation/refactor/` as a `...Body`
   or `...Section` widget. If it renders a reusable piece, it belongs in
   `presentation/widgets/`.
2. **A private `_Widget` class at the bottom of a body file** is fine while it is
   small and used once. Once a second file wants it, it moves to `widgets/`.
3. **Branching on state inside the widget** is not a layout problem, it is a
   cubit problem. Move the decision, not the markup.

## What a screen looks like at the right size

```dart
class ArchiveScreen extends StatelessWidget {
  const ArchiveScreen({super.key, this.onLessonTap});

  final ValueChanged<LessonModel>? onLessonTap;

  @override
  Widget build(BuildContext context) {
    return BlocProvider<ArchiveCubit>(
      create: (_) => getIt<ArchiveCubit>(),
      child: BlocListener<ArchiveCubit, ArchiveState>(
        listenWhen: (previous, current) =>
            current.errorKey != null && current.items != null,
        listener: _showRefreshError,
        child: AppSectionScaffold(
          title: LangKeys.savedItems.tr(),
          child: ArchiveBody(onLessonTap: onLessonTap),
        ),
      ),
    );
  }
}
```

Everything visual is in `ArchiveBody`. The screen wires and nothing else.

## Responsive constraints that cause the usual crash

* `Expanded` / `Flexible` only inside a parent that bounds them — a `Column`
  inside a `SingleChildScrollView` does not.
* Long text always gets `maxLines` plus `overflow`.
* Wrap content in `SafeArea`; use `Wrap` where a `Row` would overflow.

```dart
// wrong - unbounded height inside a scroll view
SingleChildScrollView(
  child: Column(
    children: [Expanded(child: list)],    // R10
  ),
)

// right - give it a real bound
SingleChildScrollView(
  child: Column(
    children: [SizedBox(height: 240, child: list)],
  ),
)
```

Checked by rules R3, R4 and R10. `flutter_refactor_plan` lists a file's largest
methods with a suggested destination for each.
