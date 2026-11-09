class CarModel {
  final int id;
  final String? carBrand;
  final String? carModel;
  final String? carNumber;
  final String? vin;
  final String? mileage;

  CarModel({
    required this.id,
    this.carBrand,
    this.carModel,
    this.carNumber,
    this.vin,
    this.mileage,
  });

  factory CarModel.fromJson(Map<String, dynamic> json) {
    return CarModel(
      id: json['id'] as int,
      carBrand: json['car_brand'] as String?,
      carModel: json['car_model'] as String?,
      carNumber: json['car_number'] as String?,
      vin: json['vin'] as String?,
      mileage: json['mileage'] as String?,
    );
  }

  String get displayName {
    final parts = [carBrand, carModel, carNumber].where((e) => e != null && e.isNotEmpty).toList();
    return parts.join(' ');
  }
}

class WorkHistoryItem {
  final int workId;
  final DateTime workDate;
  final String? carBrand;
  final String? carModel;
  final String? carNumber;
  final String description;
  final double amount;
  final double partsTotal;
  final String? orderNumber;
  final int? mileage;
  final List<PartItem> parts;

  WorkHistoryItem({
    required this.workId,
    required this.workDate,
    this.carBrand,
    this.carModel,
    this.carNumber,
    required this.description,
    required this.amount,
    required this.partsTotal,
    this.orderNumber,
    this.mileage,
    required this.parts,
  });

  factory WorkHistoryItem.fromJson(Map<String, dynamic> json) {
    return WorkHistoryItem(
      workId: json['work_id'] as int,
      workDate: DateTime.parse(json['work_date'] as String),
      carBrand: json['car_brand'] as String?,
      carModel: json['car_model'] as String?,
      carNumber: json['car_number'] as String?,
      description: json['description'] as String,
      amount: double.parse(json['amount'].toString()),
      partsTotal: double.parse(json['parts_total'].toString()),
      orderNumber: json['order_number'] as String?,
      mileage: json['mileage'] as int?,
      parts: (json['parts'] as List).map((e) => PartItem.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }

  double get totalCost => amount + partsTotal;
}

class PartItem {
  final String partName;
  final double partPrice;

  PartItem({required this.partName, required this.partPrice});

  factory PartItem.fromJson(Map<String, dynamic> json) {
    return PartItem(
      partName: json['part_name'] as String,
      partPrice: double.parse(json['part_price'].toString()),
    );
  }
}

class BookingModel {
  final int id;
  final DateTime bookingDate;
  final String bookingTime;
  final String status;
  final String? carDisplay;

  BookingModel({
    required this.id,
    required this.bookingDate,
    required this.bookingTime,
    required this.status,
    this.carDisplay,
  });

  factory BookingModel.fromJson(Map<String, dynamic> json) {
    return BookingModel(
      id: json['id'] as int,
      bookingDate: DateTime.parse(json['booking_date'] as String),
      bookingTime: json['booking_time'] as String,
      status: json['status'] as String,
      carDisplay: json['car_display'] as String?,
    );
  }

  String get statusDisplay {
    switch (status) {
      case 'waiting': return 'Ожидает';
      case 'in_progress': return 'В работе';
      case 'done': return 'Выполнено';
      case 'cancelled': return 'Отменено';
      default: return status;
    }
  }
}
