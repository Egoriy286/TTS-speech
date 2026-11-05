# Рассказ о MsFEM для записи

Выберите в программе записи «MsFEM — часть 1», затем следующие части. Каждый абзац записывайте отдельно, до 30 секунд.

## English

1. Imagine water moving through a piece of rock. Some regions let it pass easily, while others slow it down. These tiny differences can change the behavior of the whole system.

2. A very fine mesh can describe those details, but solving a large problem on that mesh may be expensive. The multiscale finite element method uses a different strategy for the global calculation.

3. We divide the domain into larger elements. Inside each one, we solve local problems on a fine mesh. Their solutions form special basis functions that reflect the material's small scale structure.

4. We then use these basis functions to assemble a smaller global system on the coarse mesh. This can reduce the global computational cost, while keeping important information from the local material structure.

## Russian

1. Представьте, как вода проходит через кусок горной породы. Одни участки легко пропускают поток, а другие его замедляют. Эти небольшие различия могут менять поведение всей системы.

2. Очень мелкая сетка позволяет описать такие детали, но решение большой задачи на этой сетке может стоить дорого. Многомасштабный метод конечных элементов предлагает другой подход к глобальному расчёту.

3. Мы делим область на крупные элементы. Внутри каждого из них решаем локальные задачи на мелкой сетке. Полученные решения образуют специальные базисные функции, которые учитывают мелкую структуру материала.

4. Затем с помощью этих базисных функций мы собираем меньшую глобальную систему на крупной сетке. Это позволяет уменьшить стоимость глобального расчёта и сохранить важную информацию о локальной структуре материала.

Научная основа: [Hou & Wu, 1997 — оригинальная статья](https://users.cms.caltech.edu/~hou/papers/msfemjcp.pdf). Рассказ написан заново для устной подачи.
