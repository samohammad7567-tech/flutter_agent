# Pattern: screen, body, widget

Source: `bilhikma/lib/features/archive/presentation/`. The split that keeps a
screen at 42 lines.

## Screen — wiring only

```dart
class ArchiveScreen extends StatelessWidget {
  const ArchiveScreen({super.key, this.onLessonTap});

  final ValueChanged<LessonModel>? onLessonTap;

  @override
  Widget build(BuildContext context) {
    return BlocProvider<ArchiveCubit>(
      create: (_) => getIt<ArchiveCubit>(),
      child: BlocListener<ArchiveCubit, ArchiveState>(
        listenWhen: (ArchiveState previous, ArchiveState current) =>
            current.errorKey != null && current.items != null,
        listener: _showRefreshError,
        child: AppSectionScaffold(
          title: LangKeys.savedItems.tr(),
          child: ArchiveBody(onLessonTap: onLessonTap),
        ),
      ),
    );
  }

  /// A refresh that fails over existing data is a toast, not an error page.
  void _showRefreshError(BuildContext context, ArchiveState state) {
    final String? errorKey = state.errorKey;
    if (errorKey == null) return;

    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(errorKey.tr())));
  }
}
```

Four things and no more: provide the cubit, listen for the toast case, give the
scaffold a translated title, hand the body down. `_showRefreshError` is allowed
here because it is a listener callback, not a `_build...` layout method.

## Body — reads state, holds no logic

The body is where `BlocBuilder` lives and where state becomes widgets. Every
branch it takes is a getter the cubit already computed.

```dart
BlocBuilder<ArchiveCubit, ArchiveState>(
  builder: (BuildContext context, ArchiveState state) {
    if (state.isFirstLoad) return const Center(child: CircularProgressIndicator());
    if (state.hasFailed) return AppErrorState(messageKey: state.errorKey);
    if (state.visibleItems.isEmpty) return const AppEmptyState();

    return RefreshIndicator(
      onRefresh: context.read<ArchiveCubit>().refresh,
      child: ListView.builder(
        itemCount: state.visibleItems.length,
        itemBuilder: (context, index) =>
            ArchiveTile(item: state.visibleItems[index], onTap: onLessonTap),
      ),
    );
  },
)
```

Note the branch order — first load, then failure, then empty, then content. Doing
empty before first load renders an empty state during the initial spinner.

`onRefresh` is the cubit method passed directly as a tear-off; wrapping it in a
closure that also touches context is how navigation leaks back into the body.

## Widget — dumb, reusable, reports upward

```dart
class ArchiveTile extends StatelessWidget {
  const ArchiveTile({super.key, required this.item, this.onTap});

  final LessonModel item;
  final ValueChanged<LessonModel>? onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap == null ? null : () => onTap!(item),
      title: Text(item.title, maxLines: 2, overflow: TextOverflow.ellipsis),
    );
  }
}
```

A widget never reads the cubit it happens to sit under. It takes what it renders
and emits what was tapped, which is what lets the same tile appear on the archive
screen, in search results, and in a bottom sheet.

## Before writing any widget

Check the shared package first — `AppButton`, `AppTextField`, `AppCard`,
`AppAvatar`, `AppEmptyState`, `AppErrorState`, `AppLoadingOverlay`, `SettingRow`
and more already exist. `flutter_component` with no argument lists them.
