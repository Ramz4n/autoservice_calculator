import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/car.dart';
import '../models/user.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';
import 'login_screen.dart';

class SettingsScreen extends StatefulWidget {
  final UserModel user;
  final List<CarModel> cars;

  const SettingsScreen({super.key, required this.user, required this.cars});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _changed = false;

  void _showSuccess(String msg) {
    setState(() => _changed = true);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.green),
    );
  }

  void _showError(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.red),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: true,
      onPopInvoked: (_) {},
      child: Scaffold(
        appBar: AppBar(title: const Text('Настройки')),
        body: ListView(
          children: [
            _sectionHeader('Личные данные'),
            ListTile(
              leading: const Icon(Icons.person_outline),
              title: const Text('Имя и телефон'),
              subtitle: Text(widget.user.displayName),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _openEditProfile(),
            ),
            ListTile(
              leading: const Icon(Icons.email_outlined),
              title: const Text('Изменить email'),
              subtitle: Text(widget.user.email),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _openChangeEmail(),
            ),
            ListTile(
              leading: const Icon(Icons.lock_outline),
              title: const Text('Изменить пароль'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _openChangePassword(),
            ),
            const Divider(),
            _sectionHeader('Автомобили'),
            if (widget.cars.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Text('Нет автомобилей', style: TextStyle(color: Colors.grey)),
              )
            else
              ...widget.cars.map((car) => ListTile(
                    leading: const Icon(Icons.directions_car_outlined),
                    title: Text(car.displayName),
                    subtitle: const Text('Удалить (история сохранится)'),
                    trailing: IconButton(
                      icon: const Icon(Icons.delete_outline, color: Colors.red),
                      onPressed: () => _deleteCar(car),
                    ),
                  )),
            const Divider(),
            _sectionHeader('Аккаунт'),
            ListTile(
              leading: const Icon(Icons.logout, color: Colors.red),
              title: const Text('Выйти', style: TextStyle(color: Colors.red)),
              onTap: _logout,
            ),
          ],
        ),
      ),
    );
  }

  Widget _sectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(title,
          style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.bold,
              color: Colors.grey.shade600,
              letterSpacing: 0.8)),
    );
  }

  void _openEditProfile() {
    final nameCtrl = TextEditingController(text: widget.user.fullName ?? '');
    final phoneCtrl = TextEditingController(text: widget.user.phone ?? '');
    bool saving = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModal) => Padding(
          padding: EdgeInsets.fromLTRB(
              24, 24, 24, MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Личные данные',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(
                    labelText: 'Имя', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: phoneCtrl,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(
                    labelText: 'Телефон', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                height: 46,
                child: ElevatedButton(
                  onPressed: saving
                      ? null
                      : () async {
                          setModal(() => saving = true);
                          try {
                            await context.read<ApiService>().updateProfile(
                                  fullName: nameCtrl.text.trim(),
                                  phone: phoneCtrl.text.trim(),
                                );
                            if (mounted) Navigator.pop(ctx);
                            _showSuccess('Данные обновлены');
                          } catch (e) {
                            _showError(e.toString().replaceFirst('Exception: ', ''));
                          } finally {
                            setModal(() => saving = false);
                          }
                        },
                  child: saving
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Сохранить'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _openChangePassword() {
    final currentCtrl = TextEditingController();
    final newCtrl = TextEditingController();
    final confirmCtrl = TextEditingController();
    bool saving = false;
    String? error;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModal) => Padding(
          padding: EdgeInsets.fromLTRB(
              24, 24, 24, MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Изменить пароль',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              TextField(
                controller: currentCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                    labelText: 'Текущий пароль', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: newCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                    labelText: 'Новый пароль', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: confirmCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                    labelText: 'Повторите новый пароль',
                    border: OutlineInputBorder()),
              ),
              if (error != null) ...[
                const SizedBox(height: 8),
                Text(error!, style: const TextStyle(color: Colors.red, fontSize: 13)),
              ],
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                height: 46,
                child: ElevatedButton(
                  onPressed: saving
                      ? null
                      : () async {
                          if (newCtrl.text != confirmCtrl.text) {
                            setModal(() => error = 'Пароли не совпадают');
                            return;
                          }
                          if (newCtrl.text.length < 6) {
                            setModal(() => error = 'Минимум 6 символов');
                            return;
                          }
                          setModal(() { saving = true; error = null; });
                          try {
                            await context.read<ApiService>().changePassword(
                                  currentPassword: currentCtrl.text,
                                  newPassword: newCtrl.text,
                                );
                            if (mounted) Navigator.pop(ctx);
                            _showSuccess('Пароль изменён');
                          } catch (e) {
                            setModal(() => error = e.toString().replaceFirst('Exception: ', ''));
                          } finally {
                            setModal(() => saving = false);
                          }
                        },
                  child: saving
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Изменить пароль'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _openChangeEmail() {
    final emailCtrl = TextEditingController();
    final passwordCtrl = TextEditingController();
    bool saving = false;
    String? error;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModal) => Padding(
          padding: EdgeInsets.fromLTRB(
              24, 24, 24, MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Изменить email',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              TextField(
                controller: emailCtrl,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                    labelText: 'Новый email', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: passwordCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                    labelText: 'Текущий пароль (для подтверждения)',
                    border: OutlineInputBorder()),
              ),
              if (error != null) ...[
                const SizedBox(height: 8),
                Text(error!, style: const TextStyle(color: Colors.red, fontSize: 13)),
              ],
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                height: 46,
                child: ElevatedButton(
                  onPressed: saving
                      ? null
                      : () async {
                          setModal(() { saving = true; error = null; });
                          try {
                            await context.read<ApiService>().changeEmail(
                                  email: emailCtrl.text.trim(),
                                  currentPassword: passwordCtrl.text,
                                );
                            if (mounted) Navigator.pop(ctx);
                            _showSuccess('Email изменён');
                          } catch (e) {
                            setModal(() => error = e.toString().replaceFirst('Exception: ', ''));
                          } finally {
                            setModal(() => saving = false);
                          }
                        },
                  child: saving
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Изменить email'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _deleteCar(CarModel car) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Удалить автомобиль?'),
        content: Text(
            '${car.displayName}\n\nИстория обслуживания сохранится в базе данных.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await context.read<ApiService>().deleteCar(car.id);
      setState(() => _changed = true);
      _showSuccess('Автомобиль удалён. История сохранена.');
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      _showError(e.toString().replaceFirst('Exception: ', ''));
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
}
