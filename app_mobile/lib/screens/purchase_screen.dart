import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/subscription.dart';
import '../services/api_service.dart';

class PurchaseScreen extends StatefulWidget {
  final SubscriptionPlan plan;

  const PurchaseScreen({super.key, required this.plan});

  @override
  State<PurchaseScreen> createState() => _PurchaseScreenState();
}

class _PurchaseScreenState extends State<PurchaseScreen> with WidgetsBindingObserver {
  bool _loading = false;
  bool _success = false;
  bool _waitingPayment = false;
  String? _error;
  String? _paymentId;
  Timer? _pollTimer;

  static const _planColors = {
    'basic': Colors.green,
    'premium': Colors.blue,
    'vip': Colors.amber,
  };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  // Когда пользователь возвращается в приложение из браузера — начинаем проверку
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _waitingPayment && _paymentId != null) {
      _startPolling();
    }
  }

  Future<void> _purchase() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final result = await api.purchaseSubscription(widget.plan.plan);
      final confirmationUrl = result['confirmation_url'] as String?;
      final paymentId = result['payment_id'] as String?;

      if (confirmationUrl == null || paymentId == null) {
        throw Exception('Не удалось получить ссылку для оплаты');
      }

      _paymentId = paymentId;

      // Открываем ЮКасса в браузере
      final uri = Uri.parse(confirmationUrl);
      if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        throw Exception('Не удалось открыть браузер');
      }

      if (mounted) {
        setState(() {
          _loading = false;
          _waitingPayment = true;
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

  void _startPolling() {
    _pollTimer?.cancel();
    int attempts = 0;
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (timer) async {
      attempts++;
      if (attempts > 30) { // максимум 2 минуты
        timer.cancel();
        return;
      }
      try {
        final api = context.read<ApiService>();
        final result = await api.checkPaymentStatus(_paymentId!);
        final status = result['status'] as String?;
        if (status == 'succeeded') {
          timer.cancel();
          if (mounted) setState(() { _success = true; _waitingPayment = false; });
        } else if (status == 'canceled') {
          timer.cancel();
          if (mounted) {
            setState(() {
              _waitingPayment = false;
              _error = 'Платёж отменён';
            });
          }
        }
      } catch (_) {}
    });
  }

  @override
  Widget build(BuildContext context) {
    final plan = widget.plan;
    final color = _planColors[plan.plan] ?? Colors.blue;
    final formatter = NumberFormat.currency(locale: 'ru_RU', symbol: '₽', decimalDigits: 0);

    return Scaffold(
      appBar: AppBar(title: const Text('Оформление подписки')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: _success
              ? _buildSuccessView(formatter)
              : _waitingPayment
                  ? _buildWaitingView(color)
                  : _buildPaymentView(plan, color, formatter),
        ),
      ),
    );
  }

  Widget _buildPaymentView(SubscriptionPlan plan, Color color, NumberFormat formatter) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Card(
          elevation: 2,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: color, width: 1.5),
          ),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(plan.name,
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: color)),
                const SizedBox(height: 4),
                Text('${formatter.format(plan.price)} / год',
                    style: const TextStyle(fontSize: 18)),
                const Divider(height: 24),
                ...plan.features.map((f) => Padding(
                      padding: const EdgeInsets.only(bottom: 7),
                      child: Row(children: [
                        Icon(Icons.check_circle_outline, size: 18, color: color),
                        const SizedBox(width: 8),
                        Expanded(child: Text(f)),
                      ]),
                    )),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.grey.shade100,
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Row(
            children: [
              Icon(Icons.info_outline, color: Colors.grey),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Нажмите "Оплатить" — откроется браузер с формой оплаты ЮКасса.\nТестовая карта: 4111 1111 1111 1111',
                  style: TextStyle(color: Colors.grey, fontSize: 13),
                ),
              ),
            ],
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.red.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.red.shade200),
            ),
            child: Row(children: [
              const Icon(Icons.error_outline, color: Colors.red, size: 18),
              const SizedBox(width: 8),
              Expanded(child: Text(_error!, style: const TextStyle(color: Colors.red))),
            ]),
          ),
        ],
        const Spacer(),
        SizedBox(
          width: double.infinity,
          height: 54,
          child: ElevatedButton(
            onPressed: _loading ? null : _purchase,
            style: ElevatedButton.styleFrom(
                backgroundColor: color, foregroundColor: Colors.white),
            child: _loading
                ? const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text('Оплатить ${formatter.format(widget.plan.price)}',
                    style: const TextStyle(fontSize: 17)),
          ),
        ),
      ],
    );
  }

  Widget _buildWaitingView(Color color) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          CircularProgressIndicator(color: color),
          const SizedBox(height: 24),
          const Text('Ожидание оплаты...',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          const Text(
            'После оплаты вернитесь в приложение.\nПодписка активируется автоматически.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 32),
          OutlinedButton(
            onPressed: _startPolling,
            child: const Text('Я оплатил — проверить статус'),
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: () {
              _pollTimer?.cancel();
              setState(() { _waitingPayment = false; });
            },
            child: const Text('Отмена', style: TextStyle(color: Colors.grey)),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccessView(NumberFormat formatter) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.check_circle_rounded, color: Colors.green, size: 90),
          const SizedBox(height: 20),
          const Text('Подписка оформлена!',
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(widget.plan.name, style: const TextStyle(fontSize: 16, color: Colors.grey)),
          const SizedBox(height: 6),
          Text('${formatter.format(widget.plan.price)} / год',
              style: const TextStyle(fontSize: 16)),
          const SizedBox(height: 40),
          ElevatedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Вернуться к подпискам'),
          ),
        ],
      ),
    );
  }
}
