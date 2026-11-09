import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/car.dart';
import '../services/api_service.dart';

class CarHistoryScreen extends StatefulWidget {
  final CarModel car;

  const CarHistoryScreen({super.key, required this.car});

  @override
  State<CarHistoryScreen> createState() => _CarHistoryScreenState();
}

class _CarHistoryScreenState extends State<CarHistoryScreen> {
  List<WorkHistoryItem>? _history;
  bool _loading = true;
  String? _error;

  final _moneyFmt = NumberFormat.currency(locale: 'ru_RU', symbol: '₽', decimalDigits: 0);
  final _dateFmt = DateFormat('dd.MM.yyyy');

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final data = await api.getCarHistory(widget.car.id);
      setState(() {
        _history = data.map((e) => WorkHistoryItem.fromJson(e as Map<String, dynamic>)).toList();
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.car.displayName),
        bottom: const PreferredSize(
          preferredSize: Size.fromHeight(20),
          child: Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text('История обслуживания',
                style: TextStyle(color: Colors.white70, fontSize: 13)),
          ),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: Colors.red)))
              : _history == null || _history!.isEmpty
                  ? const Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.history, size: 64, color: Colors.grey),
                          SizedBox(height: 12),
                          Text('История обслуживания пуста',
                              style: TextStyle(color: Colors.grey, fontSize: 16)),
                        ],
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: ListView.builder(
                        padding: const EdgeInsets.all(16),
                        itemCount: _history!.length,
                        itemBuilder: (_, i) => _buildWorkCard(_history![i]),
                      ),
                    ),
    );
  }

  Widget _buildWorkCard(WorkHistoryItem item) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ExpansionTile(
        leading: const CircleAvatar(
          backgroundColor: Colors.blue,
          child: Icon(Icons.build, color: Colors.white, size: 20),
        ),
        title: Text(
          _dateFmt.format(item.workDate),
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              item.description,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 13),
            ),
            Text(
              'Итого: ${_moneyFmt.format(item.totalCost)}',
              style: const TextStyle(
                  color: Colors.blue, fontWeight: FontWeight.w600, fontSize: 13),
            ),
          ],
        ),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Divider(),
                Text('Описание работ:', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey.shade700)),
                const SizedBox(height: 4),
                Text(item.description),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _infoChip(Icons.handyman, 'Работа: ${_moneyFmt.format(item.amount)}'),
                    const SizedBox(width: 8),
                    _infoChip(Icons.settings, 'Запчасти: ${_moneyFmt.format(item.partsTotal)}'),
                  ],
                ),
                if (item.mileage != null) ...[
                  const SizedBox(height: 8),
                  _infoChip(Icons.speed, 'Пробег: ${item.mileage} км'),
                ],
                if (item.orderNumber != null) ...[
                  const SizedBox(height: 4),
                  Text('Заказ-наряд: ${item.orderNumber}',
                      style: const TextStyle(color: Colors.grey, fontSize: 12)),
                ],
                if (item.parts.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text('Запчасти:', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey.shade700)),
                  const SizedBox(height: 4),
                  ...item.parts.map(
                    (p) => Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Row(
                        children: [
                          const Icon(Icons.circle, size: 6, color: Colors.grey),
                          const SizedBox(width: 8),
                          Expanded(child: Text(p.partName, style: const TextStyle(fontSize: 13))),
                          Text(_moneyFmt.format(p.partPrice),
                              style: const TextStyle(fontSize: 13, color: Colors.grey)),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _infoChip(IconData icon, String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.blue.shade50,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Colors.blue),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(fontSize: 12, color: Colors.blue)),
        ],
      ),
    );
  }
}
