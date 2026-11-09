class SubscriptionPlan {
  final String plan;
  final String name;
  final double price;
  final List<String> features;

  SubscriptionPlan({
    required this.plan,
    required this.name,
    required this.price,
    required this.features,
  });

  factory SubscriptionPlan.fromJson(Map<String, dynamic> json) {
    return SubscriptionPlan(
      plan: json['plan'] as String,
      name: json['name'] as String,
      price: double.parse(json['price'].toString()),
      features: List<String>.from(json['features'] as List),
    );
  }
}

class SubscriptionDetail {
  final int id;
  final String plan;
  final String status;
  final DateTime? startedAt;
  final DateTime? expiresAt;
  final double? amount;

  SubscriptionDetail({
    required this.id,
    required this.plan,
    required this.status,
    this.startedAt,
    this.expiresAt,
    this.amount,
  });

  factory SubscriptionDetail.fromJson(Map<String, dynamic> json) {
    return SubscriptionDetail(
      id: json['id'] as int,
      plan: json['plan'] as String,
      status: json['status'] as String,
      startedAt: json['started_at'] != null ? DateTime.parse(json['started_at'] as String) : null,
      expiresAt: json['expires_at'] != null ? DateTime.parse(json['expires_at'] as String) : null,
      amount: json['amount'] != null ? double.parse(json['amount'].toString()) : null,
    );
  }
}

class ActiveSubscription {
  final bool hasActive;
  final SubscriptionDetail? subscription;
  final List<String> services;

  ActiveSubscription({
    required this.hasActive,
    this.subscription,
    required this.services,
  });

  factory ActiveSubscription.fromJson(Map<String, dynamic> json) {
    return ActiveSubscription(
      hasActive: json['has_active'] as bool,
      subscription: json['subscription'] != null
          ? SubscriptionDetail.fromJson(json['subscription'] as Map<String, dynamic>)
          : null,
      services: List<String>.from(json['services'] as List),
    );
  }
}
