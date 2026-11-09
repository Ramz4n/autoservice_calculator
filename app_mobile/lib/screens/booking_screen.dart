import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/car.dart';
import '../services/api_service.dart';

class BookingScreen extends StatefulWidget {
  final List<CarModel> cars;

  const BookingScreen({super.key, required this.cars});

  @override
  State<BookingScreen> createState() => _BookingScreenState();
}

class _BookingScreenState extends State<BookingScreen> {
  DateTime _selectedDate = DateTime.now().add(const Duration(days: 1));
  String? _selectedSlot;
  CarModel? _selectedCar;
  List<String> _slots = [];
  bool _loadingSlots = false;
  bool _submitting = false;
  bool _success = false;
  String? _error;

  final _dateFmt = DateFormat('dd.MM.yyyy');

  @override
  void initState() {
    super.initState();
    _loadSlots();
  }

  Future<void> _loadSlots() async {
    setState(() { _loadingSlots = true; _selectedSlot = null; _error = null; });
    try {
      final api = context.read<ApiService>();
      final dateStr = DateFormat('yyyy-MM-dd').format(_selectedDate);
      final data = await api.getAvailableSlots(dateStr);
      setState(() {
        _slots = List<String>.from(data['slots'] as List);
        _loadingSlots = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loadingSlots = false;
      });
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 60)),
      locale: const Locale('ru'),
    );
    if (picked != null && picked != _selectedDate) {
      setState(() => _selectedDate = picked);
      _loadSlots();
    }
  }

  Future<void> _submit() async {
    if (_selectedSlot == null) return;
    setState(() { _submitting = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      await api.createBooking(
        bookingDate: DateFormat('yyyy-MM-dd').format(_selectedDate),
        bookingTime: _selectedSlot!,
        carId: _selectedCar?.id,
      );
      setState(() { _success = true; _submitting = false; });
    } catch (e) {
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Запись в сервис')),
      body: _success ? _buildSuccess() : _buildForm(),
    );
  }

  Widget _buildForm() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Выбор авто
          if (widget.cars.isNotEmpty) ...[
            Text('Автомобиль', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            DropdownButtonFormField<CarModel>(
              value: _selectedCar,
              hint: const Text('Выберите автомобиль (необязательно)'),
              decoration: const InputDecoration(border: OutlineInputBorder()),
              items: widget.cars.map((car) => DropdownMenuItem(
                value: car,
                child: Text(car.displayName),
              )).toList(),
              onChanged: (v) => setState(() => _selectedCar = v),
            ),
            const SizedBox(height: 20),
          ],

          // Выбор даты
          Text('Дата', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          InkWell(
            onTap: _pickDate,
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                border: Border.all(color: Colors.grey.shade400),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Row(
                children: [
                  const Icon(Icons.calendar_today, color: Colors.blue),
                  const SizedBox(width: 12),
                  Text(_dateFmt.format(_selectedDate),
                      style: const TextStyle(fontSize: 16)),
                  const Spacer(),
                  const Icon(Icons.arrow_drop_down, color: Colors.grey),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Выбор времени
          Text('Время', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (_loadingSlots)
            const Center(child: CircularProgressIndicator())
          else if (_slots.isEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.orange.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.orange.shade200),
              ),
              child: const Row(
                children: [
                  Icon(Icons.info_outline, color: Colors.orange),
                  SizedBox(width: 8),
                  Text('Нет свободных слотов на эту дату'),
                ],
              ),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: _slots.map((slot) {
                final selected = _selectedSlot == slot;
                return GestureDetector(
                  onTap: () => setState(() => _selectedSlot = slot),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                    decoration: BoxDecoration(
                      color: selected ? Colors.blue : Colors.white,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: selected ? Colors.blue : Colors.grey.shade300),
                    ),
                    child: Text(
                      slot,
                      style: TextStyle(
                        color: selected ? Colors.white : Colors.black,
                        fontWeight: selected ? FontWeight.bold : FontWeight.normal,
                        fontSize: 16,
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),

          if (_error != null) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.red.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.red.shade200),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, color: Colors.red, size: 18),
                  const SizedBox(width: 8),
                  Expanded(child: Text(_error!, style: const TextStyle(color: Colors.red))),
                ],
              ),
            ),
          ],

          const SizedBox(height: 28),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton(
              onPressed: (_selectedSlot == null || _submitting) ? null : _submit,
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blue,
                foregroundColor: Colors.white,
              ),
              child: _submitting
                  ? const SizedBox(
                      width: 22,
                      height: 22,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text(
                      _selectedSlot == null
                          ? 'Выберите время'
                          : 'Записаться на ${_dateFmt.format(_selectedDate)} в $_selectedSlot',
                      style: const TextStyle(fontSize: 15),
                    ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccess() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.check_circle_rounded, color: Colors.green, size: 90),
            const SizedBox(height: 20),
            const Text('Запись создана!',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Text(
              '${_dateFmt.format(_selectedDate)} в $_selectedSlot',
              style: const TextStyle(fontSize: 18, color: Colors.grey),
            ),
            if (_selectedCar != null) ...[
              const SizedBox(height: 8),
              Text(_selectedCar!.displayName,
                  style: const TextStyle(fontSize: 15)),
            ],
            const SizedBox(height: 40),
            ElevatedButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Готово'),
            ),
          ],
        ),
      ),
    );
  }
}
