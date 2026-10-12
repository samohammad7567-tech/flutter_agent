import '../localization/lang_keys.dart';

/// The single error type data sources throw.
///
/// [key] is always a translatable key the UI can pass straight to
/// `context.translate`, so no layer above the data source formats a message.
class AppException implements Exception {
  const AppException(this.key);

  final String key;

  @override
  String toString() => 'AppException($key)';
}

/// Reduces any error to one stable translation key. Called in the data source
/// or the cubit's catch-all arm — never twice for the same error.
class ErrorMapper {
  ErrorMapper._();

  static String map(Object error) {
    if (error is AppException) return error.key;
    return LangKeys.somethingWentWrong;
  }
}
