# Errors: one exception type, one stable key, mapped once

Error mapping happens in the data source, exactly once. The cubit carries a key;
the UI translates it. No layer duplicates the mapping.

## The shape, from `bilhikma/lib/core/utils/error_mapper.dart`

```dart
/// The single error type data sources throw.
///
/// [key] is always a translatable key the UI can pass straight to
/// `context.translate`. [message] carries the server's own text, which the API
/// has already localized from `Accept-Language` - prefer it when present.
class AppException implements Exception {
  const AppException(
    this.key, {
    this.message,
    this.errors = const <String, List<String>>{},
    this.statusCode,
    this.data,
  });

  final String key;
  final String? message;
  final Map<String, List<String>> errors;   // field-keyed 422 messages
  final int? statusCode;
  final Object? data;

  List<String> errorsFor(String field) => errors[field] ?? const <String>[];
  bool get hasFieldErrors => errors.isNotEmpty;
}

class ErrorMapper {
  ErrorMapper._();

  static String map(Object error) {
    if (error is AppException) return error.key;
    if (error is DioException) return _mapDio(error);
    return LangKeys.somethingWentWrong;
  }
}
```

## The cubit side

Catch the known exception for its key, then catch everything else through the
mapper. Both arms guard with `isClosed`.

```dart
Future<void> _load() async {
  try {
    final List<LessonModel> items = await repo.fetchSavedItems(
      type: state.selectedFilter.mediaType,
    );
    if (isClosed) return;

    emit(
      state.copyWith(
        status: items.isEmpty ? ArchiveStatus.empty : ArchiveStatus.success,
        items: items,
        clearError: true,
      ),
    );
  } on AppException catch (error) {
    if (isClosed) return;
    emit(state.copyWith(status: ArchiveStatus.failure, errorKey: error.key));
  } catch (error) {
    if (isClosed) return;
    emit(
      state.copyWith(
        status: ArchiveStatus.failure,
        errorKey: ErrorMapper.map(error),
      ),
    );
  }
}
```

## Two kinds of failure, two presentations

A first load that fails has nothing to show, so it becomes a full error state.
A refresh that fails over existing data must not blank the screen, so it becomes
a toast. The state distinguishes them; the screen reads the distinction.

```dart
bool get hasFailed => status == ArchiveStatus.failure && items == null;
```

```dart
BlocListener<ArchiveCubit, ArchiveState>(
  // errorKey set AND items present == a failed refresh, not a failed load
  listenWhen: (previous, current) =>
      current.errorKey != null && current.items != null,
  listener: _showRefreshError,
  child: ...,
)
```

## Why `clearError` exists rather than passing null

`copyWith` cannot distinguish "leave it alone" from "set it to null" when the
field is nullable, so a successful load would silently keep the stale key. The
explicit flag is the fix:

```dart
ArchiveState copyWith({
  ArchiveStatus? status,
  List<LessonModel>? items,
  String? errorKey,
  bool clearError = false,
}) => ArchiveState(
  status: status ?? this.status,
  items: items ?? this.items,
  errorKey: clearError ? null : errorKey ?? this.errorKey,
);
```

Checked by rule R5 (no error mapping in presentation) and R6.
