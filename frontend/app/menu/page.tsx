import type { Metadata } from 'next';
import { Clock3, Flame, Leaf, Plus, Search, Star } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Меню партнера',
  description: 'Мобильное меню для гостей партнера.',
};

type MenuItem = {
  name: string;
  description: string;
  price: number;
  weight: string;
  badges?: Array<'hit' | 'vegan' | 'spicy'>;
};

type MenuSection = {
  title: string;
  subtitle: string;
  items: MenuItem[];
};

const sections: MenuSection[] = [
  {
    title: 'Завтраки',
    subtitle: 'До 13:00',
    items: [
      {
        name: 'Сырники с ягодами',
        description: 'Творожные сырники, сметана, клубничный соус и свежие ягоды.',
        price: 520,
        weight: '230 г',
        badges: ['hit'],
      },
      {
        name: 'Омлет с лососем',
        description: 'Три яйца, слабосоленый лосось, крем-сыр, зелень и тост.',
        price: 690,
        weight: '260 г',
      },
      {
        name: 'Авокадо-тост',
        description: 'Ржаной хлеб, авокадо, яйцо пашот, томаты и микрозелень.',
        price: 610,
        weight: '210 г',
        badges: ['vegan'],
      },
    ],
  },
  {
    title: 'Закуски',
    subtitle: 'Легко начать',
    items: [
      {
        name: 'Брускетта с томатами',
        description: 'Чиабатта, сладкие томаты, базилик, оливковое масло и пармезан.',
        price: 430,
        weight: '180 г',
        badges: ['vegan'],
      },
      {
        name: 'Креветки темпура',
        description: 'Хрустящие креветки, соус айоли и лайм.',
        price: 760,
        weight: '190 г',
        badges: ['hit'],
      },
      {
        name: 'Хумус с питой',
        description: 'Нут, тахини, печеный перец, зелень и теплая пита.',
        price: 390,
        weight: '240 г',
        badges: ['vegan'],
      },
    ],
  },
  {
    title: 'Основное',
    subtitle: 'Горячие блюда',
    items: [
      {
        name: 'Паста с грибами',
        description: 'Тальятелле, белые грибы, сливочный соус и выдержанный сыр.',
        price: 780,
        weight: '320 г',
      },
      {
        name: 'Курица терияки',
        description: 'Куриное бедро, рис жасмин, брокколи, кунжут и соус терияки.',
        price: 720,
        weight: '360 г',
        badges: ['hit'],
      },
      {
        name: 'Боул с тунцом',
        description: 'Тунец, рис, эдамаме, огурец, манго, нори и ореховый соус.',
        price: 890,
        weight: '340 г',
      },
      {
        name: 'Том ям с морепродуктами',
        description: 'Креветки, кальмар, шампиньоны, кокосовое молоко и рис.',
        price: 840,
        weight: '410 г',
        badges: ['spicy'],
      },
    ],
  },
  {
    title: 'Десерты',
    subtitle: 'К кофе и после ужина',
    items: [
      {
        name: 'Чизкейк ванильный',
        description: 'Классический чизкейк, ягодный соус и миндальная крошка.',
        price: 420,
        weight: '150 г',
      },
      {
        name: 'Шоколадный фондан',
        description: 'Теплый шоколадный кекс с жидким центром и мороженым.',
        price: 490,
        weight: '170 г',
        badges: ['hit'],
      },
      {
        name: 'Панна-котта манго',
        description: 'Сливочная панна-котта, манго, маракуйя и мята.',
        price: 440,
        weight: '160 г',
      },
    ],
  },
  {
    title: 'Напитки',
    subtitle: 'Горячее и холодное',
    items: [
      {
        name: 'Капучино',
        description: 'Эспрессо и молоко с плотной бархатной пеной.',
        price: 260,
        weight: '250 мл',
      },
      {
        name: 'Матча латте',
        description: 'Японская матча, молоко на выбор и легкая сладость.',
        price: 340,
        weight: '300 мл',
        badges: ['vegan'],
      },
      {
        name: 'Лимонад малина-базилик',
        description: 'Малина, базилик, лимонный сок и содовая.',
        price: 360,
        weight: '350 мл',
        badges: ['hit'],
      },
    ],
  },
];

const badgeConfig = {
  hit: { label: 'Хит', className: 'bg-amber-100 text-amber-800', icon: Star },
  vegan: { label: 'Вег', className: 'bg-emerald-100 text-emerald-800', icon: Leaf },
  spicy: { label: 'Остро', className: 'bg-rose-100 text-rose-800', icon: Flame },
};

function formatPrice(price: number) {
  return new Intl.NumberFormat('ru-RU').format(price);
}

export default function PartnerMenuPage() {
  const itemCount = sections.reduce((sum, section) => sum + section.items.length, 0);

  return (
    <main className="min-h-screen bg-slate-200 text-slate-950">
      <div className="mx-auto min-h-screen w-full max-w-md bg-white shadow-soft">
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 px-4 pb-3 pt-4 backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Partner cafe</p>
              <h1 className="mt-1 text-2xl font-semibold leading-tight tracking-normal text-slate-950">Меню</h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1">
                  <Clock3 className="size-3.5" />
                  Сегодня до 23:00
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-1">{itemCount} позиций</span>
              </div>
            </div>
            <button
              type="button"
              className="grid size-10 shrink-0 place-items-center rounded-full bg-slate-950 text-white shadow-pill"
              aria-label="Поиск по меню"
              title="Поиск"
            >
              <Search className="size-4" />
            </button>
          </div>
          <nav className="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1" aria-label="Разделы меню">
            {sections.map((section) => (
              <a
                key={section.title}
                href={`#${section.title}`}
                className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700"
              >
                {section.title}
              </a>
            ))}
          </nav>
        </header>

        <section className="px-4 py-4">
          <div className="overflow-hidden rounded-lg bg-slate-950 text-white">
            <div className="bg-[linear-gradient(135deg,rgba(20,97,59,0.9),rgba(29,79,138,0.45)_52%,rgba(139,31,31,0.5))] px-4 py-5">
              <p className="text-xs font-medium text-slate-200">Новое сезонное меню</p>
              <h2 className="mt-1 text-xl font-semibold tracking-normal">Все блюда доступны для заказа гостями</h2>
              <p className="mt-2 max-w-[18rem] text-sm leading-5 text-slate-200">
                Горячие блюда, завтраки, десерты и напитки в одном мобильном меню.
              </p>
            </div>
          </div>
        </section>

        <div className="space-y-6 px-4 pb-8">
          {sections.map((section) => (
            <section key={section.title} id={section.title} className="scroll-mt-32">
              <div className="mb-3 flex items-end justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold tracking-normal text-slate-950">{section.title}</h2>
                  <p className="mt-0.5 text-xs text-slate-500">{section.subtitle}</p>
                </div>
                <span className="text-xs font-medium text-slate-500">{section.items.length}</span>
              </div>

              <div className="space-y-3">
                {section.items.map((item) => (
                  <article
                    key={item.name}
                    className="rounded-lg border border-slate-200 bg-white p-3 shadow-pill"
                  >
                    <div className="flex gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <h3 className="text-[15px] font-semibold leading-5 tracking-normal text-slate-950">
                            {item.name}
                          </h3>
                          <p className="shrink-0 text-[15px] font-semibold text-slate-950">
                            {formatPrice(item.price)} ₽
                          </p>
                        </div>
                        <p className="mt-1.5 text-[13px] leading-5 text-slate-600">{item.description}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-1.5">
                          <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600">
                            {item.weight}
                          </span>
                          {item.badges?.map((badge) => {
                            const config = badgeConfig[badge];
                            const Icon = config.icon;
                            return (
                              <span
                                key={badge}
                                className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium ${config.className}`}
                              >
                                <Icon className="size-3" />
                                {config.label}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="mt-auto grid size-9 shrink-0 place-items-center rounded-full bg-slate-950 text-white shadow-pill"
                        aria-label={`Добавить ${item.name}`}
                        title="Добавить"
                      >
                        <Plus className="size-4" />
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
