import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/user.dart';
import '../models/subscription.dart';
import '../models/car.dart';
import 'my_bookings_screen.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';
import 'login_screen.dart';
import 'subscriptions_screen.dart';
import 'car_history_screen.dart';
import 'booking_screen.dart';
import 'settings_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  UserModel? _user;
  ActiveSubscription? _subscription;
  List<CarModel> _cars = [];
  BookingModel? _nextBooking;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiService>();
      final profileData = await api.getProfile();
      final subData = await api.getMySubscription();
      final carsData = await api.getMyCars();
      final bookingsData = await api.getMyBookings();
      if (mounted) {
        final now = DateTime.now();
        final upcoming = bookingsData
            .map((e) => BookingModel.fromJson(e as Map<String, dynamic>))
            .where((b) =>
                (b.status == 'waiting' || b.status == 'in_progress') &&
                !b.bookingDate.isBefore(DateTime(now.year, now.month, now.day)))
            .toList();
        upcoming.sort((a, b) => a.bookingDate.compareTo(b.bookingDate));
        setState(() {
          _user = UserModel.fromJson(profileData);
          _subscription = ActiveSubscription.fromJson(subData);
          _cars = carsData.map((e) => CarModel.fromJson(e as Map<String, dynamic>)).toList();
          _nextBooking = upcoming.isNotEmpty ? upcoming.first : null;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString().replaceFirst('Exception: ', '');
          _loading = false;
        });
      }
    }
  }

  Color _subscriptionBgColor() {
    final plan = _subscription?.subscription?.plan;
    switch (plan) {
      case 'basic': return Colors.green.shade50;
      case 'premium': return Colors.blue.shade50;
      case 'vip': return Colors.amber.shade50;
      default: return Colors.grey.shade50;
    }
  }

  Color _subscriptionAppBarColor() {
    final plan = _subscription?.subscription?.plan;
    switch (plan) {
      case 'basic': return Colors.green.shade100;
      case 'premium': return Colors.blue.shade100;
      case 'vip': return Colors.amber.shade100;
      default: return Colors.grey.shade100;
    }
  }

  Future<void> _logout() async {
    final storage = context.read<StorageService>();
    await storage.deleteToken();
    if (mounted) {
      Navigator.pushAndRemoveUntil(
        context,
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (_) => false,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _loading ? Colors.grey.shade50 : _subscriptionBgColor(),
      appBar: AppBar(
        backgroundColor: _loading ? Colors.grey.shade100 : _subscriptionAppBarColor(),
        title: const Text('Профиль'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Настройки',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => SettingsScreen(user: _user!, cars: _cars),
              ),
            ).then((_) => _loadData()),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.error_outline, size: 48, color: Colors.red),
                      const SizedBox(height: 12),
                      Text(_error!, style: const TextStyle(color: Colors.red)),
                      const SizedBox(height: 16),
                      ElevatedButton(onPressed: _loadData, child: const Text('Повторить')),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (_nextBooking != null) _buildBookingBanner(_nextBooking!),
                      if (_nextBooking != null) const SizedBox(height: 16),
                      _buildUserCard(),
                      const SizedBox(height: 16),
                      _buildSubscriptionCard(),
                      const SizedBox(height: 16),
                      _buildCarsSection(),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        height: 50,
                        child: ElevatedButton.icon(
                          onPressed: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                                builder: (_) => BookingScreen(cars: _cars)),
                          ),
                          icon: const Icon(Icons.calendar_month),
                          label: const Text('Записаться в сервис',
                              style: TextStyle(fontSize: 16)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green,
                            foregroundColor: Colors.white,
                          ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        height: 50,
                        child: ElevatedButton.icon(
                          onPressed: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                                builder: (_) => const SubscriptionsScreen()),
                          ).then((_) => _loadData()),
                          icon: const Icon(Icons.card_membership),
                          label: const Text('Управление подпиской',
                              style: TextStyle(fontSize: 16)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.blue,
                            foregroundColor: Colors.white,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
    );
  }

  Widget _buildUserCard() {
    final user = _user!;
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 30,
                  backgroundColor: Colors.blue,
                  child: Text(
                    user.initials,
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 24,
                        fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        user.displayName,
                        style: Theme.of(context)
                            .textTheme
                            .titleLarge
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      Text(user.email,
                          style: const TextStyle(color: Colors.grey)),
                    ],
                  ),
                ),
              ],
            ),
            const Divider(height: 24),
            if (user.phone != null && user.phone!.isNotEmpty) ...[
              _infoRow(Icons.phone, 'Телефон', user.phone!),
              const SizedBox(height: 6),
            ],
            _infoRow(
              Icons.badge_outlined,
              'Роль',
              user.role == 'admin' ? 'Администратор' : 'Клиент',
            ),
            const SizedBox(height: 6),
            _infoRow(
              Icons.calendar_today,
              'Зарегистрирован',
              DateFormat('dd.MM.yyyy').format(user.createdAt),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBookingBanner(BookingModel booking) {
    final dateFmt = DateFormat('dd.MM.yyyy');
    return InkWell(
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const MyBookingsScreen()),
      ).then((_) => _loadData()),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.green.shade50,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.green.shade300),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.green,
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.calendar_month, color: Colors.white, size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Вы записаны в сервис',
                      style: TextStyle(fontWeight: FontWeight.bold, color: Colors.green)),
                  Text(
                    '${dateFmt.format(booking.bookingDate)} в ${booking.bookingTime}',
                    style: const TextStyle(fontSize: 15),
                  ),
                  if (booking.carDisplay != null && booking.carDisplay!.isNotEmpty)
                    Text(booking.carDisplay!,
                        style: const TextStyle(color: Colors.grey, fontSize: 13)),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: Colors.green),
          ],
        ),
      ),
    );
  }

  Widget _buildCarsSection() {
    if (_cars.isEmpty) {
      return Card(
        color: Colors.grey.shade50,
        child: const Padding(
          padding: EdgeInsets.all(16),
          child: Row(
            children: [
              Icon(Icons.directions_car, color: Colors.grey),
              SizedBox(width: 12),
              Text('Автомобили не найдены', style: TextStyle(color: Colors.grey)),
            ],
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Мои автомобили',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        ..._cars.map((car) => _buildCarTile(car)),
      ],
    );
  }

  Widget _buildCarTile(CarModel car) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: const CircleAvatar(
          backgroundColor: Colors.blue,
          child: Icon(Icons.directions_car, color: Colors.white, size: 20),
        ),
        title: Text(car.displayName, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (car.vin != null && car.vin!.isNotEmpty)
              Text('VIN: ${car.vin}', style: const TextStyle(fontSize: 12, color: Colors.grey)),
            if (car.mileage != null && car.mileage!.isNotEmpty)
              Text('Пробег: ${car.mileage} км', style: const TextStyle(fontSize: 12, color: Colors.grey)),
          ],
        ),
        trailing: TextButton.icon(
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => CarHistoryScreen(car: car)),
          ),
          icon: const Icon(Icons.history, size: 18),
          label: const Text('История'),
        ),
      ),
    );
  }

  Widget _infoRow(IconData icon, String label, String value) {
    return Row(
      children: [
        Icon(icon, size: 18, color: Colors.grey),
        const SizedBox(width: 8),
        Text('$label: ', style: const TextStyle(color: Colors.grey)),
        Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
      ],
    );
  }

  Widget _buildSubscriptionCard() {
    final sub = _subscription;

    if (sub == null || !sub.hasActive) {
      return Card(
        color: Colors.orange.shade50,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Icon(Icons.warning_amber_rounded, color: Colors.orange.shade700, size: 28),
              const SizedBox(width: 12),
              const Expanded(
                child: Text(
                  'Нет активной подписки.\nОформите подписку для доступа к услугам автосервиса.',
                ),
              ),
            ],
          ),
        ),
      );
    }

    final detail = sub.subscription!;
    final planColors = {
      'basic': Colors.green,
      'premium': Colors.blue,
      'vip': Colors.amber.shade700,
    };
    final planNames = {'basic': 'Basic', 'premium': 'Premium', 'vip': 'VIP'};
    final color = planColors[detail.plan] ?? Colors.blue;

    return Card(
      elevation: 3,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: color, width: 1.5),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.verified_rounded, color: color, size: 26),
                const SizedBox(width: 8),
                Text(
                  'Подписка ${planNames[detail.plan] ?? detail.plan}',
                  style: TextStyle(
                      fontWeight: FontWeight.bold, color: color, fontSize: 17),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.green.shade100,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text('Активна',
                      style: TextStyle(color: Colors.green, fontSize: 12)),
                ),
              ],
            ),
            if (detail.expiresAt != null) ...[
              const SizedBox(height: 8),
              Text(
                'Действует до: ${DateFormat('dd.MM.yyyy').format(detail.expiresAt!)}',
                style: const TextStyle(color: Colors.grey),
              ),
            ],
            const Divider(height: 20),
            Text(
              'Доступные услуги:',
              style: TextStyle(fontWeight: FontWeight.bold, color: color),
            ),
            const SizedBox(height: 8),
            ...sub.services.map(
              (s) => Padding(
                padding: const EdgeInsets.only(bottom: 5),
                child: Row(
                  children: [
                    Icon(Icons.check_circle_outline, size: 16, color: color),
                    const SizedBox(width: 8),
                    Expanded(child: Text(s, style: const TextStyle(fontSize: 13))),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
