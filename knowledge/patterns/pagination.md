# Pattern: paginated lists

Source: `bilhikma/lib/core/network/paginated_result.dart`,
`pagination_meta.dart`, and `features/lessons/presentation/cubit/lessons_cubit.dart`.

## The envelope

A list endpoint answers with `data.items` plus `data.meta.pagination`. One
generic type carries both, so no feature re-parses the envelope.

```dart
/// A `data.items` + `data.meta.pagination` list page.
class PaginatedResult<T> {
  const PaginatedResult({required this.items, this.meta = const PaginationMeta()});

  final List<T> items;
  final PaginationMeta meta;

  bool get isEmpty => items.isEmpty;
  bool get hasMore => meta.hasMore;

  /// Parses the `data` object of a list endpoint.
  factory PaginatedResult.fromData(
    Map<String, dynamic> data,
    T Function(Map<String, dynamic> json) parse,
  ) => PaginatedResult<T>(
    items: Json.asList<T>(data['items'], parse),
    meta: PaginationMeta.fromData(data),
  );

  /// Some endpoints answer with a bare array, or an `items` list carrying no
  /// pagination block.
  factory PaginatedResult.fromDynamic(
    Object? data,
    T Function(Map<String, dynamic> json) parse,
  ) {
    if (data is List) {
      return PaginatedResult<T>(items: Json.asList<T>(data, parse));
    }
    return PaginatedResult<T>.fromData(Json.asMap(data), parse);
  }
}
```

`fromDynamic` is the important one: the backend is not consistent about whether a
list endpoint returns an array or an envelope, and that inconsistency is absorbed
here rather than in five different data sources.

## Filtering is a request, not a client-side filter

Each tab or chip is its own call. The cubit does not hold the full list and
filter it in Dart — the type goes to the server as `filter[type]`.

```dart
/// Switches the lecture/audio/article tab. Each tab is its own request -
/// `filter[type]` is what backs them.
Future<void> selectType(ContentType type) async {
  if (type == state.selectedType) return;

  emit(state.copyWith(selectedType: type, status: LessonsStatus.loading));
  await _loadLessons(type);
}

Future<void> _loadLessons(ContentType type) async {
  final PaginatedResult<LessonModel> page = await repo.fetchLessons(
    LessonsFilter(categorySubjectId: categorySubjectId, type: type),
  );
  if (isClosed) return;
  emit(state.copyWith(status: LessonsStatus.success, page: page));
}
```

A widget that filters a list in its `build` is a rule violation (R5 in spirit,
and the reason the list flickers): the filter is state, and state lives in the
cubit.

## The filter object

Multi-field filters get their own model in `data/models/`, so the data source
signature does not grow a parameter per field and the cubit can compare filters
for equality to skip no-op requests.

## Loading more

`hasMore` comes from the meta block, never from `items.length < total` guessed in
the UI. The cubit appends; the state keeps the latest meta.

```dart
Future<void> loadMore() async {
  if (!state.page.hasMore || state.isLoadingMore) return;
  emit(state.copyWith(isLoadingMore: true));

  final PaginatedResult<LessonModel> next =
      await repo.fetchLessons(state.filter.copyWith(page: state.page.meta.currentPage + 1));
  if (isClosed) return;

  emit(state.copyWith(
    page: PaginatedResult<LessonModel>(
      items: [...state.page.items, ...next.items],
      meta: next.meta,
    ),
    isLoadingMore: false,
  ));
}
```

The guard on the first line is what stops a fast scroll from firing the same page
request three times.
