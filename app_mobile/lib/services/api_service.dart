import 'dart:convert';
import 'package:http/http.dart' as http;
import 'storage_service.dart';

class ApiService {
  // Реальный Android-телефон: IP твоего компьютера в локальной сети
  // Узнать IP: ipconfig (Windows) → "IPv4-адрес" того адаптера, к которому подключён Wi-Fi
  // Пример: http://192.168.1.105:8000
  // Эмулятор Android: http://10.0.2.2:8000
  // iOS симулятор: http://localhost:8000
  static const String baseUrl = 'http://192.168.31.154:8000';

  final StorageService _storage;

  ApiService(this._storage);

  Future<Map<String, String>> _authHeaders() async {
    final token = await _storage.getToken();
    return {
      'Content-Type': 'application/json; charset=utf-8',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Map<String, dynamic> _decodeBody(http.Response response) {
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  List<dynamic> _decodeListBody(http.Response response) {
    return jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
  }

  void _checkStatus(http.Response response) {
    if (response.statusCode >= 400) {
      final body = _decodeBody(response);
      throw Exception(body['detail'] ?? 'Ошибка запроса (${response.statusCode})');
    }
  }

  // --- Auth ---

  Future<Map<String, dynamic>> register({
    required String email,
    required String password,
    String? fullName,
    String? phone,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/register'),
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({
        'email': email,
        'password': password,
        if (fullName != null && fullName.isNotEmpty) 'full_name': fullName,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
      }),
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({'email': email, 'password': password}),
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  // --- Profile ---

  Future<Map<String, dynamic>> getProfile() async {
    final headers = await _authHeaders();
    final response = await http.get(Uri.parse('$baseUrl/clients/me'), headers: headers);
    _checkStatus(response);
    return _decodeBody(response);
  }

  // --- Subscriptions ---

  Future<List<dynamic>> getPlans() async {
    final response = await http.get(Uri.parse('$baseUrl/subscriptions/plans'));
    _checkStatus(response);
    return _decodeListBody(response);
  }

  Future<Map<String, dynamic>> getMySubscription() async {
    final headers = await _authHeaders();
    final response =
        await http.get(Uri.parse('$baseUrl/subscriptions/my'), headers: headers);
    _checkStatus(response);
    return _decodeBody(response);
  }

  // --- Payments ---

  Future<Map<String, dynamic>> purchaseSubscription(String plan) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/payments/purchase'),
      headers: headers,
      body: jsonEncode({'plan': plan}),
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  Future<Map<String, dynamic>> checkPaymentStatus(String paymentId) async {
    final headers = await _authHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/payments/status/$paymentId'),
      headers: headers,
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  Future<List<dynamic>> getPaymentHistory() async {
    final headers = await _authHeaders();
    final response =
        await http.get(Uri.parse('$baseUrl/payments/history'), headers: headers);
    _checkStatus(response);
    return _decodeListBody(response);
  }

  // --- Cars ---

  Future<List<dynamic>> getMyCars() async {
    final headers = await _authHeaders();
    final response = await http.get(Uri.parse('$baseUrl/cars/my'), headers: headers);
    _checkStatus(response);
    return _decodeListBody(response);
  }

  Future<List<dynamic>> getCarHistory(int carId) async {
    final headers = await _authHeaders();
    final response = await http.get(Uri.parse('$baseUrl/cars/$carId/history'), headers: headers);
    _checkStatus(response);
    return _decodeListBody(response);
  }

  // --- Bookings ---

  Future<Map<String, dynamic>> getAvailableSlots(String date) async {
    final response = await http.get(
      Uri.parse('$baseUrl/bookings/slots?booking_date=$date'),
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  Future<Map<String, dynamic>> createBooking({
    required String bookingDate,
    required String bookingTime,
    int? carId,
  }) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/bookings/create'),
      headers: headers,
      body: jsonEncode({
        'booking_date': bookingDate,
        'booking_time': bookingTime,
        if (carId != null) 'car_id': carId,
      }),
    );
    _checkStatus(response);
    return _decodeBody(response);
  }

  Future<List<dynamic>> getMyBookings() async {
    final headers = await _authHeaders();
    final response = await http.get(Uri.parse('$baseUrl/bookings/my'), headers: headers);
    _checkStatus(response);
    return _decodeListBody(response);
  }

  Future<void> cancelBooking(int bookingId) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/bookings/$bookingId/cancel'),
      headers: headers,
    );
    _checkStatus(response);
  }

  Future<void> deleteCar(int carId) async {
    final headers = await _authHeaders();
    final response = await http.delete(
      Uri.parse('$baseUrl/cars/$carId'),
      headers: headers,
    );
    _checkStatus(response);
  }

  Future<void> updateProfile({String? fullName, String? phone}) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/settings/profile'),
      headers: headers,
      body: jsonEncode({
        if (fullName != null) 'full_name': fullName,
        if (phone != null) 'phone': phone,
      }),
    );
    _checkStatus(response);
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/settings/password'),
      headers: headers,
      body: jsonEncode({
        'current_password': currentPassword,
        'new_password': newPassword,
      }),
    );
    _checkStatus(response);
  }

  Future<void> changeEmail({
    required String email,
    required String currentPassword,
  }) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/settings/email'),
      headers: headers,
      body: jsonEncode({
        'email': email,
        'current_password': currentPassword,
      }),
    );
    _checkStatus(response);
  }
}
